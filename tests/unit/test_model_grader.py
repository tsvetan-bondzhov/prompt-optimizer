"""Unit tests: ModelGrader (LLM-as-judge) verdict parsing and configuration."""

from __future__ import annotations

import json

from app.core.registry import register
from app.implementations.model_grader import ModelGrader
from app.llm.base import LLMRunner
from app.models import PromptResult, TestCase


class ScriptedJudge(LLMRunner):
    """Returns a scripted response and records the prompts it received."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        options: dict | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


VERDICT = {
    "score": 8,
    "strengths": ["accurate", "concise"],
    "weaknesses": ["misses one edge case"],
    "reasoning": "Mostly correct with a minor omission.",
}


def make_case(criteria: dict, per_entry: list[dict] | None = None) -> TestCase:
    return TestCase(
        name="tc",
        grader_names=["model_grader"],
        evaluation_criteria=criteria,
        evaluation_criteria_per_entry=per_entry or [],
    )


async def test_grades_via_runner_from_criteria():
    judge = ScriptedJudge(json.dumps(VERDICT))
    register("llm_runner", "scripted-judge", lambda: judge)
    case = make_case(
        {"evaluation_prompt": "Judge factual accuracy.", "llm_runner": "scripted-judge"}
    )

    evaluation = await ModelGrader().grade(PromptResult(text="The answer"), case)

    assert evaluation.score == 8
    assert evaluation.strengths == ["accurate", "concise"]
    assert evaluation.weaknesses == ["misses one edge case"]
    assert evaluation.grader_name == "model_grader"
    system_prompt, user_prompt = judge.calls[0]
    assert "Judge factual accuracy." in user_prompt
    assert "The answer" in user_prompt


async def test_fenced_verdict_tolerated():
    judge = ScriptedJudge(f"```json\n{json.dumps(VERDICT)}\n```")
    register("llm_runner", "scripted-judge", lambda: judge)
    case = make_case(
        {"evaluation_prompt": "Judge.", "llm_runner": "scripted-judge"}
    )
    evaluation = await ModelGrader().grade(PromptResult(text="x"), case)
    assert evaluation.score == 8


async def test_per_entry_criteria_override_dataset():
    judge = ScriptedJudge(json.dumps(VERDICT))
    register("llm_runner", "scripted-judge", lambda: judge)
    case = make_case(
        {"evaluation_prompt": "dataset-level prompt", "llm_runner": "scripted-judge"},
        per_entry=[
            {"evaluation_prompt": "entry-level prompt", "llm_runner": "scripted-judge"}
        ],
    )
    await ModelGrader().grade(PromptResult(text="x"), case, entry_index=0)
    assert "entry-level prompt" in judge.calls[0][1]


async def test_missing_evaluation_prompt_is_neutral():
    evaluation = await ModelGrader().grade(
        PromptResult(text="x"), make_case({})
    )
    assert evaluation.score == 5
    assert any("evaluation_prompt" in w for w in evaluation.weaknesses)


async def test_unparseable_verdict_scores_1():
    judge = ScriptedJudge("I refuse to answer in JSON.")
    register("llm_runner", "scripted-judge", lambda: judge)
    case = make_case(
        {"evaluation_prompt": "Judge.", "llm_runner": "scripted-judge"}
    )
    evaluation = await ModelGrader().grade(PromptResult(text="x"), case)
    assert evaluation.score == 1
    assert any("failed" in w.lower() for w in evaluation.weaknesses)


async def test_out_of_range_score_clamped():
    verdict = dict(VERDICT, score=42)
    judge = ScriptedJudge(json.dumps(verdict))
    register("llm_runner", "scripted-judge", lambda: judge)
    case = make_case(
        {"evaluation_prompt": "Judge.", "llm_runner": "scripted-judge"}
    )
    evaluation = await ModelGrader().grade(PromptResult(text="x"), case)
    assert evaluation.score == 10
