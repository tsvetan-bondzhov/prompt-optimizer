"""Deterministic, offline :class:`LLMRunner` for tests and local development.

``FakeLLMRunner`` performs no external calls and returns a stable, templated
echo of the composed prompt, making it suitable for unit/integration tests and
offline work. Activate it by registering under ``("llm_runner", "fake")`` and
setting ``ACTIVE_LLM_RUNNER=fake``.
"""

from __future__ import annotations

from app.llm.base import LLMRunner, compose_prompt

__all__ = ["FakeLLMRunner"]


class FakeLLMRunner(LLMRunner):
    """Return deterministic output derived from the input prompts (no I/O)."""

    def __init__(self, prefix: str = "[fake]") -> None:
        """:param prefix: Marker prepended to the echoed output."""

        self._prefix = prefix

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        options: dict | None = None,
    ) -> str:
        """Echo the composed prompt deterministically, with no external calls."""

        return f"{self._prefix} {compose_prompt(system_prompt, user_prompt)}".strip()
