"""Default :class:`LLMRunner` backed by Claude Code headless (``claude -p``).

``ClaudeCodeRunner`` shells out to the Claude Code CLI in headless / print mode
via :func:`asyncio.create_subprocess_exec` (never blocking the event loop). The
composed ``system + user`` prompt is passed on stdin and the CLI's stdout is
returned as the result text.

To swap this default for another backend (Cursor / Copilot / Anthropic API),
write a new :class:`~app.llm.base.LLMRunner` subclass, register it under a new
``("llm_runner", "<name>")`` key, and set ``ACTIVE_LLM_RUNNER=<name>`` — no
service edits required. See :mod:`app.llm.base` for the full swap recipe.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.llm.base import LLMRunner, LLMRunnerError, compose_prompt

__all__ = ["ClaudeCodeRunner"]

# Default wall-clock budget for a single CLI invocation, in seconds.
DEFAULT_TIMEOUT_SECONDS: float = 120.0


class ClaudeCodeRunner(LLMRunner):
    """Run prompts through the Claude Code CLI in headless (``-p``) mode."""

    def __init__(
        self,
        cli_path: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        extra_args: list[str] | None = None,
    ) -> None:
        """Configure the runner.

        :param cli_path: Path to the ``claude`` executable. Defaults to
            ``settings.CLAUDE_CLI_PATH`` when not provided.
        :param timeout: Per-invocation timeout in seconds.
        :param extra_args: Additional CLI arguments inserted before the prompt
            flag (useful for model selection, etc.).
        """

        self._cli_path = cli_path or get_settings().CLAUDE_CLI_PATH
        self._timeout = timeout
        self._extra_args = list(extra_args or [])

    async def run(self, system_prompt: str, user_prompt: str) -> str:
        """Invoke ``claude -p`` with the composed prompt; return stdout text.

        Raises :class:`LLMRunnerError` if the CLI is missing, exits non-zero, or
        does not complete within the configured timeout.
        """

        prompt = compose_prompt(system_prompt, user_prompt)
        args = [self._cli_path, *self._extra_args, "-p"]

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise LLMRunnerError(
                f"Claude Code CLI not found at {self._cli_path!r}. "
                "Set CLAUDE_CLI_PATH to a valid executable."
            ) from exc
        except OSError as exc:  # pragma: no cover - defensive
            raise LLMRunnerError(
                f"Failed to launch Claude Code CLI {self._cli_path!r}: {exc}"
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            _terminate(process)
            raise LLMRunnerError(
                f"Claude Code CLI timed out after {self._timeout:g}s."
            ) from exc

        if process.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise LLMRunnerError(
                f"Claude Code CLI exited with code {process.returncode}: "
                f"{stderr_text or '<no stderr>'}"
            )

        return stdout_bytes.decode("utf-8", errors="replace").strip()


def _terminate(process: asyncio.subprocess.Process) -> None:
    """Best-effort kill of a still-running subprocess after a timeout."""

    try:
        process.kill()
    except ProcessLookupError:  # pragma: no cover - already exited
        pass
