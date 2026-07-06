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

    Metadata (shown in the UI): ``display_name`` is the human-readable label,
    ``description`` explains the executor's purpose, and ``criteria_info`` /
    ``criteria_sample`` document any evaluation-criteria keys it reads
    (usually none for executors).
    """

    #: Human-readable name shown in the UI (falls back to the registry name).
    display_name: str = ""
    #: Short explanation of what this executor does, shown in the info popup.
    description: str = ""
    #: Documented criteria keys: ``[{"key": ..., "description": ...}, ...]``.
    criteria_info: list[dict[str, str]] = []
    #: Copy-pasteable sample evaluation criteria (JSON-serializable) or None.
    criteria_sample: Any = None

    @abstractmethod
    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict[str, Any],
        llm_runner: LLMRunner,
    ) -> PromptResult:
        """Run ``prompt`` against one data ``entry`` of ``test_case``.

        ``llm_runner`` is the runner selected on the test case
        (``TestCase.executor_llm_runner``); executors that do not call an LLM
        may ignore it.
        """
        raise NotImplementedError


class Grader(ABC):
    """Scores a single :class:`PromptResult` and returns a structured evaluation.

    User-supplied. A grader ships no built-in LLM call — the scoring logic is
    entirely up to the implementation. Each grader exposes a ``name`` used for
    traceability in persisted reports.

    Graders are invoked once per data entry; :meth:`criteria_for` resolves the
    criteria to grade against **per key**: a key present in the entry's own
    criteria wins, every other key falls back to the dataset-level criteria.

    Metadata (shown in the UI): ``display_name`` is the human-readable label,
    ``description`` explains the grader's purpose, and ``criteria_info`` /
    ``criteria_sample`` document the evaluation-criteria keys it consumes.
    """

    name: str
    #: Human-readable name shown in the UI (falls back to ``name``).
    display_name: str = ""
    #: Short explanation of what this grader scores, shown in the info popup.
    description: str = ""
    #: Documented criteria keys: ``[{"key": ..., "description": ...}, ...]``.
    criteria_info: list[dict[str, str]] = []
    #: Copy-pasteable sample evaluation criteria (JSON-serializable) or None.
    criteria_sample: Any = None

    def criteria_for(
        self, test_case: TestCase, entry_index: int
    ) -> dict[str, Any]:
        """Effective criteria for ``entry_index``, resolved key by key.

        Each key comes from the entry's own criteria when present there and
        from the dataset-level ``evaluation_criteria`` otherwise, so e.g.
        ``expected_json`` can be set per entry while ``json_schema`` is set
        once for the whole dataset.
        """

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
        self,
        evaluations: list[PromptEvaluation],
        llm_runner: LLMRunner | None = None,
    ) -> EvaluationSummary:
        """Merge ``evaluations`` into one :class:`EvaluationSummary`.

        ``llm_runner`` is the runner selected for summarization (from the test
        case's ``summarizer_llm_runner``); ``None`` means use the active
        default. Non-LLM summarizers may ignore it.
        """
        raise NotImplementedError


class LLMRunner(ABC):
    """A minimal text-in / text-out LLM interface used by optimizer/summarizer.

    ``options_schema`` documents the runner-specific options the UI offers
    wherever this runner can be selected. Each item:
    ``{"name", "label", "type" ("text"|"number"), "default"}``. The selected
    values are stored with the test case / prompt and handed back through the
    ``options`` argument of :meth:`run`; runners without options ignore it.
    """

    #: Runner-specific option fields presented in the UI (may be empty).
    options_schema: list[dict[str, Any]] = []

    @abstractmethod
    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Run the LLM with the given prompts and return the response text.

        :param options: Runner-specific options (see ``options_schema``);
            ``None`` or missing keys mean "use the runner's defaults".
        """
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
