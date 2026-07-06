"""Unit tests: runner-specific LLM options (claude/ollama) and binding."""

from __future__ import annotations

import pytest

from app.core.interfaces import LLMRunner
from app.core.registry import register
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
)
from app.core.interfaces import mean_aggregator
from app.llm.base import ConfiguredLLMRunner
from app.llm.claude_code import option_args
from app.llm.ollama import OllamaLLMRunner
from app.models import PromptText, TestCase
from app.services.evaluator import EvaluatorService
from app.implementations.template_executor import TemplateExecutor
from tests.fakes import FakeGrader


class RecordingRunner(LLMRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        options: dict | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_prompt, options))
        return "out"


# -- claude CLI option mapping -------------------------------------------------


def test_claude_option_args_maps_flags():
    assert option_args(
        {"model": "claude-sonnet-4-6", "effort": "high", "temperature": 0.2}
    ) == [
        "--model",
        "claude-sonnet-4-6",
        "--effort",
        "high",
        "--temperature",
        "0.2",
    ]


def test_claude_option_args_ignores_empty_values():
    assert option_args({"model": "  ", "effort": "", "temperature": None}) == []
    assert option_args(None) == []
    assert option_args({}) == []


# -- ollama payload --------------------------------------------------------------


def test_ollama_payload_defaults():
    payload = OllamaLLMRunner.build_payload("sys", "user", None)
    assert payload["model"] == "mistral"
    assert "options" not in payload


def test_ollama_payload_applies_model_and_temperature():
    payload = OllamaLLMRunner.build_payload(
        "sys", "user", {"model": "llama3", "temperature": 0.7}
    )
    assert payload["model"] == "llama3"
    assert payload["options"] == {"temperature": 0.7}


def test_ollama_payload_ignores_empty_options():
    payload = OllamaLLMRunner.build_payload(
        "sys", "user", {"model": "", "temperature": ""}
    )
    assert payload["model"] == "mistral"
    assert "options" not in payload


# -- ConfiguredLLMRunner ---------------------------------------------------------


async def test_configured_runner_binds_options():
    inner = RecordingRunner()
    runner = ConfiguredLLMRunner(inner, {"model": "m1", "temperature": 0.1})
    await runner.run("sys", "user")
    assert inner.calls == [("sys", "user", {"model": "m1", "temperature": 0.1})]


async def test_configured_runner_per_call_options_win():
    inner = RecordingRunner()
    runner = ConfiguredLLMRunner(inner, {"model": "m1"})
    await runner.run("sys", "user", {"model": "m2"})
    assert inner.calls[0][2] == {"model": "m2"}


# -- evaluator binds the test case's executor runner options ---------------------


async def test_evaluator_passes_executor_runner_options(db):
    inner = RecordingRunner()
    register("llm_runner", "recording", lambda: inner)

    grader = FakeGrader(scores=(8,))
    evaluator = EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=lambda name: TemplateExecutor(),
        grader_resolver=lambda name: grader,
        llm_runner_resolver=lambda name: inner,
        aggregator_resolver=lambda: mean_aggregator,
    )
    test_case = TestCase(
        name="tc",
        data=[{"x": "1"}],
        grader_names=["fake-step"],
        executor_llm_runner="recording",
        executor_llm_runner_options={"model": "claude-sonnet-4-6", "effort": "low"},
    )
    await evaluator.run(PromptText(text="say {x}"), [test_case], 1)

    assert inner.calls[0][2] == {"model": "claude-sonnet-4-6", "effort": "low"}
