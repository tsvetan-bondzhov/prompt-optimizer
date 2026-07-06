"""Unit tests: NoArgsExecutor and ConcatExecutor."""

from __future__ import annotations

import json

from app.implementations.simple_executors import ConcatExecutor, NoArgsExecutor
from app.llm.base import LLMRunner
from app.models import PromptText, TestCase


class RecordingRunner(LLMRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return "out"

CASE = TestCase(name="tc", grader_names=["fake"])


async def test_no_args_passes_prompt_unchanged():
    runner = RecordingRunner()
    result = await NoArgsExecutor().execute(
        PromptText(text="just the prompt"), CASE, {"ignored": True}, runner
    )
    assert result.text == "out"
    assert runner.calls == [("", "just the prompt")]


async def test_concat_appends_serialized_entry():
    runner = RecordingRunner()
    entry = {"question": "2+2?", "hint": 4}
    await ConcatExecutor().execute(PromptText(text="Answer:"), CASE, entry, runner)
    (_, user_prompt), = runner.calls
    assert user_prompt.startswith("Answer:\n\n")
    assert json.loads(user_prompt.split("\n\n", 1)[1]) == entry


async def test_concat_with_empty_entry_keeps_prompt():
    runner = RecordingRunner()
    await ConcatExecutor().execute(PromptText(text="Answer:"), CASE, {}, runner)
    assert runner.calls == [("", "Answer:")]
