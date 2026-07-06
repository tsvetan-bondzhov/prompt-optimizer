"""LLM runner base interface, errors, and shared helpers (plan §4).

This module re-exports the :class:`~app.core.interfaces.LLMRunner` ABC so that
runner implementations can depend on ``app.llm.base`` without reaching into the
core package, and it defines the typed error and prompt-composition helper that
concrete runners share.

Swapping the active runner (e.g. to Cursor / Copilot / Anthropic API) requires
only:

1. Write a new :class:`LLMRunner` subclass (here or in ``app/llm``).
2. Register it under ``("llm_runner", "<name>")`` (see
   :func:`app.core.bootstrap.register_builtins`).
3. Point the ``ACTIVE_LLM_RUNNER`` setting at ``"<name>"``.

No service code changes are needed — services resolve the runner by name via
:func:`app.core.registry.get_llm_runner`.
"""

from __future__ import annotations

from typing import Any

from app.core.interfaces import LLMRunner

__all__ = [
    "LLMRunner",
    "LLMRunnerError",
    "ConfiguredLLMRunner",
    "compose_prompt",
]


class ConfiguredLLMRunner(LLMRunner):
    """Bind runner-specific ``options`` to a runner instance.

    Callers that hold a runner selection (test case / prompt) wrap the
    resolved runner once; downstream code (executors, summarizers) keeps
    calling the plain two-argument ``run`` without knowing about options.
    Explicit per-call options still win over the bound ones.
    """

    def __init__(
        self, runner: LLMRunner, options: dict[str, Any] | None = None
    ) -> None:
        """:param runner: The wrapped runner.
        :param options: Options forwarded to every ``run`` invocation.
        """

        self._runner = runner
        self._options = dict(options or {})

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Forward to the wrapped runner with the bound options applied."""

        merged = {**self._options, **(options or {})}
        return await self._runner.run(system_prompt, user_prompt, merged or None)


class LLMRunnerError(RuntimeError):
    """Raised when an :class:`LLMRunner` fails to produce a result.

    Covers process launch failures (missing CLI), non-zero exits, and timeouts.
    The originating ``stderr`` / context is included in the message where
    available so callers can surface actionable diagnostics.
    """


def compose_prompt(system_prompt: str, user_prompt: str) -> str:
    """Combine a system and user prompt into a single text payload.

    Kept as a small standalone helper so other runners (CLI-based or otherwise)
    that take a single prompt string can reuse the exact same composition. The
    system prompt is omitted from the combined text when empty.
    """

    system = (system_prompt or "").strip()
    user = (user_prompt or "").strip()
    if not system:
        return user
    return f"{system}\n\n{user}"
