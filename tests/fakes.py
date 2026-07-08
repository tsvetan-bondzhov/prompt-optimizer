"""Shared deterministic test doubles (Task 15). No network / LLM access."""

from __future__ import annotations

from collections import deque
from typing import Iterable, Optional

from app.core.interfaces import (
    Grader,
    PromptExecutor,
    PromptOptimizer,
    Summarizer,
)
from app.models import (
    EvaluationSummary,
    OptimizationContext,
    PromptText,
    PromptEvaluation,
    PromptResult,
    TestCase,
)


class FakeExecutor(PromptExecutor):
    """Echoes prompt + test case deterministically; counts invocations."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict | None = None,
        llm_runner=None,
    ) -> PromptResult:
        self.calls.append((prompt.text, test_case.id))
        return PromptResult(text=f"result[{test_case.name}]: {prompt.text}")


class FakeGrader(Grader):
    """Returns a scripted sequence of scores (repeating the last one)."""

    def __init__(self, name: str = "fake-step", scores: Iterable[int] = (8,)) -> None:
        self.name = name
        self._scores = deque(scores)
        self._last = self._scores[-1]
        self.calls = 0

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        self.calls += 1
        score = self._scores.popleft() if self._scores else self._last
        return PromptEvaluation(
            strengths=[f"strength-{score}"],
            weaknesses=[f"weakness-{score}"],
            reasoning=f"scripted score {score} for {test_case.name}",
            score=score,
            grader_name=self.name,
        )


class FailingGrader(Grader):
    """Always raises — used to exercise per-point failure isolation."""

    name = "failing-step"

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        raise RuntimeError("scripted step failure")


class FakeOptimizer(PromptOptimizer):
    """Returns scripted prompts (default: appends an iteration marker)."""

    def __init__(self, prompts: Optional[Iterable[str]] = None) -> None:
        self._prompts = deque(prompts or [])
        self.calls = 0

    async def optimize(self, ctx: OptimizationContext) -> PromptText:
        self.calls += 1
        if self._prompts:
            return PromptText(text=self._prompts.popleft())
        return PromptText(text=f"{ctx.current_prompt} [improved v{self.calls}]")


class FakeSummarizer(Summarizer):
    """Deterministic merge: first-seen strengths/weaknesses, joined reasoning."""

    async def summarize(
        self,
        evaluations: list[PromptEvaluation],
        llm_runner=None,
    ) -> EvaluationSummary:
        strengths: list[str] = []
        weaknesses: list[str] = []
        for e in evaluations:
            for s in e.strengths:
                if s not in strengths:
                    strengths.append(s)
            for w in e.weaknesses:
                if w not in weaknesses:
                    weaknesses.append(w)
        return EvaluationSummary(
            strengths=strengths[:3],
            weaknesses=weaknesses[:3],
            reasoning=" | ".join(e.reasoning for e in evaluations),
        )
