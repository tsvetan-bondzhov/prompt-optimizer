"""Core abstract extension points (see implementation plan §4).

These abstract base classes define the pluggable seams of the framework. Concrete
implementations are registered by name in :mod:`app.core.registry` and selected
through configuration (see :class:`app.config.Settings`).

- :class:`PromptExecutor` and :class:`EvaluationStep` / :func:`prepare_evaluation`
  are **user-supplied** (reference examples ship in ``app/implementations``).
  Evaluation steps do **not** ship a built-in LLM call — users wire their own
  scoring logic.
- :class:`PromptImprover` and :class:`Summarizer` use a pluggable
  :class:`LLMRunner` (default = Claude Code headless runner).
- :class:`Aggregator` collapses per-step scores for a single evaluation point
  into one number (default = mean).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from app.models import (
    EvaluationSummary,
    ImprovementContext,
    Prompt,
    PromptEvaluation,
    PromptResult,
    TestCase,
)

__all__ = [
    "PromptExecutor",
    "EvaluationStep",
    "PrepareEvaluation",
    "PromptImprover",
    "Summarizer",
    "LLMRunner",
    "Aggregator",
    "mean_aggregator",
]


class PromptExecutor(ABC):
    """Executes a prompt against a single test case and returns its output.

    User-supplied. The executor is responsible for whatever "running the prompt"
    means for the user's use case (an LLM call, a tool invocation, etc.).
    """

    @abstractmethod
    async def execute(self, prompt: Prompt, test_case: TestCase) -> PromptResult:
        """Run ``prompt`` against ``test_case`` and return the produced result."""
        raise NotImplementedError


class EvaluationStep(ABC):
    """Scores a single :class:`PromptResult` and returns a structured evaluation.

    User-supplied. A step ships no built-in LLM call — the scoring logic is
    entirely up to the implementation. Each step exposes a ``name`` used for
    traceability in persisted reports.
    """

    name: str

    @abstractmethod
    async def evaluate(
        self, result: PromptResult, test_case: TestCase
    ) -> PromptEvaluation:
        """Evaluate ``result`` for ``test_case`` and return a structured score."""
        raise NotImplementedError


@runtime_checkable
class PrepareEvaluation(Protocol):
    """Callable returning the ordered list of evaluation steps to run.

    User code implements this factory; the registry stores and resolves it under
    the ``evaluation_prepare`` category.
    """

    def __call__(self) -> list[EvaluationStep]:
        """Return ordered, concrete :class:`EvaluationStep` instances."""
        ...


class PromptImprover(ABC):
    """Proposes an improved prompt from the current optimization context."""

    @abstractmethod
    async def improve(self, ctx: ImprovementContext) -> Prompt:
        """Return an improved :class:`Prompt` given ``ctx``."""
        raise NotImplementedError


class Summarizer(ABC):
    """Condenses many per-step evaluations into a single summary."""

    @abstractmethod
    async def summarize(
        self, evaluations: list[PromptEvaluation]
    ) -> EvaluationSummary:
        """Merge ``evaluations`` into one :class:`EvaluationSummary`."""
        raise NotImplementedError


class LLMRunner(ABC):
    """A minimal text-in / text-out LLM interface used by improver/summarizer."""

    @abstractmethod
    async def run(self, system_prompt: str, user_prompt: str) -> str:
        """Run the LLM with the given prompts and return the response text."""
        raise NotImplementedError


@runtime_checkable
class Aggregator(Protocol):
    """Collapses a single evaluation point's per-step scores into one number."""

    def __call__(self, step_evals: list[PromptEvaluation]) -> float:
        """Aggregate ``step_evals`` into a single score."""
        ...


def mean_aggregator(step_evals: list[PromptEvaluation]) -> float:
    """Default aggregation strategy: the mean of the per-step scores.

    Returns ``0.0`` for an empty list (no steps produced a score).
    """

    if not step_evals:
        return 0.0
    return sum(e.score for e in step_evals) / len(step_evals)
