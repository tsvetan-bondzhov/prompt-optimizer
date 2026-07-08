"""Unit tests: TemplateExecutor rendering + LLM runner delegation."""

from __future__ import annotations

from app.implementations.template_executor import (
    TemplateExecutor,
    render_prompt_template,
)
from app.llm.base import LLMRunner
from app.models import PromptText, TestCase


class RecordingRunner(LLMRunner):
    """Echoes the user prompt and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        options: dict | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_prompt))
        return f"ran: {user_prompt}"


def test_placeholders_substituted_from_entry():
    rendered = render_prompt_template(
        "Hello {name}, you are {age}.", {"name": "Ada", "age": 36}
    )
    assert rendered == "Hello Ada, you are 36."


def test_escaped_braces_and_unknown_tokens():
    rendered = render_prompt_template(r"keep \{literal\} and {missing}", {})
    assert rendered == "keep {literal} and {missing}"


def test_non_string_values_json_encoded():
    rendered = render_prompt_template("data: {items}", {"items": [1, 2]})
    assert rendered == "data: [1, 2]"


async def test_execute_delegates_to_selected_runner():
    runner = RecordingRunner()
    executor = TemplateExecutor()
    test_case = TestCase(name="tc", grader_names=["fake"])

    result = await executor.execute(
        PromptText(text="Summarize {topic}."),
        test_case,
        {"topic": "graphs"},
        runner,
    )

    assert result.text == "ran: Summarize graphs."
    assert runner.calls == [("", "Summarize graphs.")]
