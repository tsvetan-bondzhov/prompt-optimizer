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

from app.core.interfaces import LLMRunner

__all__ = ["LLMRunner", "LLMRunnerError", "compose_prompt"]


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
