"""Core abstract extension points (see implementation plan §4).

These abstract base classes define the pluggable seams of the framework. Concrete
implementations are registered by name in :mod:`app.core.registry` and selected
through configuration (see :class:`app.config.Settings`).

- :class:`PromptExecutor` and :class:`Grader` are **user-supplied**
  (reference examples ship in ``app/implementations``). Graders register by
  name under the ``grader`` category and are selected per test case via
  ``TestCase.grader_names``.
- :class:`PromptOptimizer` and :class:`Summarizer` use a pluggable
  :class:`LLMRunner` (default = Claude Code headless runner).
- :class:`Aggregator` collapses per-grader scores for a single evaluation point
  into one number (default = mean).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from app.models import (
    EvaluationSummary,
    OptimizationContext,
    PromptText,
    PromptEvaluation,
    PromptResult,
    TestCase,
)

__all__ = [
    "PromptExecutor",
    "Grader",
    "PromptOptimizer",
    "Summarizer",
    "LLMRunner",
    "Aggregator",
    "mean_aggregator",
]


class PromptExecutor(ABC):
    """Executes a prompt against a single data entry of a test case.

    User-supplied. The executor is responsible for whatever "running the prompt"
    means for the user's use case (an LLM call, a tool invocation, etc.). It is
    invoked once per data entry; the entry holds the inputs for that execution.
    """

    @abstractmethod
    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict[str, Any],
    ) -> PromptResult:
        """Run ``prompt`` against one data ``entry`` of ``test_case``."""
        raise NotImplementedError


class Grader(ABC):
    """Scores a single :class:`PromptResult` and returns a structured evaluation.

    User-supplied. A grader ships no built-in LLM call — the scoring logic is
    entirely up to the implementation. Each grader exposes a ``name`` used for
    traceability in persisted reports.

    Graders are invoked once per data entry; :meth:`criteria_for` resolves the
    criteria to grade against — the entry's own criteria when present, the
    dataset-level criteria otherwise.
    """

    name: str

    def criteria_for(
        self, test_case: TestCase, entry_index: int
    ) -> dict[str, Any]:
        """Criteria for ``entry_index``: per-entry first, dataset fallback."""

        return test_case.criteria_for_entry(entry_index)

    @abstractmethod
    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        """Grade ``result`` for one data entry and return a structured score."""
        raise NotImplementedError


class PromptOptimizer(ABC):
    """Proposes an improved prompt from the current optimization context."""

    @abstractmethod
    async def optimize(self, ctx: OptimizationContext) -> PromptText:
        """Return an improved :class:`PromptText` given ``ctx``."""
        raise NotImplementedError


class Summarizer(ABC):
    """Condenses many per-grader evaluations into a single summary."""

    @abstractmethod
    async def summarize(
        self, evaluations: list[PromptEvaluation]
    ) -> EvaluationSummary:
        """Merge ``evaluations`` into one :class:`EvaluationSummary`."""
        raise NotImplementedError


class LLMRunner(ABC):
    """A minimal text-in / text-out LLM interface used by optimizer/summarizer."""

    @abstractmethod
    async def run(self, system_prompt: str, user_prompt: str) -> str:
        """Run the LLM with the given prompts and return the response text."""
        raise NotImplementedError


@runtime_checkable
class Aggregator(Protocol):
    """Collapses a single evaluation point's per-grader scores into one number."""

    def __call__(self, grader_evals: list[PromptEvaluation]) -> float:
        """Aggregate ``grader_evals`` into a single score."""
        ...


def mean_aggregator(grader_evals: list[PromptEvaluation]) -> float:
    """Default aggregation strategy: the mean of the per-grader scores.

    Returns ``0.0`` for an empty list (no steps produced a score).
    """

    if not grader_evals:
        return 0.0
    return sum(e.score for e in grader_evals) / len(grader_evals)
