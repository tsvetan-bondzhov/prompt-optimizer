"""Simple reference executors: pass-through and entry concatenation.

Two minimal :class:`PromptExecutor` implementations for prompts that need
little or no per-entry templating:

* :class:`NoArgsExecutor` (``no_args``) — sends the prompt text to the
  selected LLM runner exactly as it is, ignoring the data entry entirely.
* :class:`ConcatExecutor` (``concat``) — appends the JSON-serialized data
  entry to the prompt text, then sends the combined prompt to the selected
  LLM runner.

Both register themselves on import.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.interfaces import LLMRunner, PromptExecutor
from app.core.registry import register
from app.models import PromptResult, PromptText, TestCase

__all__ = ["NoArgsExecutor", "ConcatExecutor"]


class NoArgsExecutor(PromptExecutor):
    """Send the prompt to the LLM runner as-is, ignoring the data entry."""

    display_name = "No arguments"
    description = (
        "Sends the prompt text to the selected LLM runner exactly as it is; "
        "the data entry is ignored entirely. Useful when the prompt is fully "
        "self-contained and the data entries only carry evaluation criteria."
    )

    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict[str, Any],
        llm_runner: LLMRunner,
    ) -> PromptResult:
        """Execute ``prompt`` unchanged via ``llm_runner``."""

        output_text = await llm_runner.run("", prompt.text)
        return PromptResult(text=output_text, prompt_text=prompt.text)


class ConcatExecutor(PromptExecutor):
    """Append the serialized data entry to the prompt, then run it."""

    display_name = "Concatenate entry"
    description = (
        "Appends the JSON-serialized data entry to the prompt text "
        "(separated by a blank line) and sends the combined prompt to the "
        "selected LLM runner. An empty entry leaves the prompt unchanged."
    )

    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict[str, Any],
        llm_runner: LLMRunner,
    ) -> PromptResult:
        """Execute ``prompt`` + serialized ``entry`` via ``llm_runner``."""

        combined = prompt.text
        if entry:
            serialized = json.dumps(entry, indent=2, ensure_ascii=False)
            combined = f"{prompt.text}\n\n{serialized}"
        output_text = await llm_runner.run("", combined)
        return PromptResult(text=output_text, prompt_text=combined)


register("executor", "no_args", NoArgsExecutor)
register("executor", "concat", ConcatExecutor)
