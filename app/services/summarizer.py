"""Summarization service (Task 10).

The :class:`SummarizerService` wraps the *active* :class:`Summarizer`
implementation resolved from the registry and condenses many per-step
evaluations into a single :class:`EvaluationSummary` (consolidated strengths,
weaknesses, reasoning). That summary updates optimizer state and feeds the next
improvement step (it maps cleanly onto :class:`ImprovementContext`).

It mirrors :class:`app.services.evaluator.EvaluatorService`: the concrete
implementation is injected through a resolver that defaults to the registry
helper (:func:`app.core.registry.get_summarizer`), so nothing is hardcoded and
tests can swap in any summarizer.

The :class:`Summarizer` ABC consumes a flat ``list[PromptEvaluation]``, but the
optimization loop (Task 09) holds results as ``list[EvaluationPoint]`` (each of
which carries ``step_evaluations``). :meth:`SummarizerService.summarize` accepts
either shape and flattens points into their per-step evaluations before
delegating to the active summarizer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Union

from app.core.interfaces import Summarizer
from app.core.registry import get_summarizer
from app.models import EvaluationPoint, EvaluationSummary, PromptEvaluation

__all__ = ["SummarizerService"]

logger = logging.getLogger(__name__)

# Resolver callable (defaults to the registry helper, overridable for tests).
SummarizerResolver = Callable[[], Summarizer]

# Either a list of points (loop-internal shape) or already-flat evaluations.
SummarizeInput = Sequence[Union[EvaluationPoint, PromptEvaluation]]


class SummarizerService:
    """Condense many evaluations into a single :class:`EvaluationSummary`."""

    def __init__(
        self,
        *,
        summarizer_resolver: SummarizerResolver = get_summarizer,
    ) -> None:
        """:param summarizer_resolver: Returns the active :class:`Summarizer`."""

        self._summarizer_resolver = summarizer_resolver

    async def summarize(self, points: SummarizeInput) -> EvaluationSummary:
        """Merge ``points`` into a single :class:`EvaluationSummary`.

        :param points: Either a sequence of :class:`EvaluationPoint` (the loop's
            ``eval_result.points``) or a flat sequence of
            :class:`PromptEvaluation`. Points are flattened into their per-step
            evaluations before delegation.
        :returns: The consolidated summary produced by the active summarizer.
        """

        evaluations = self._flatten(points)
        summarizer = self._summarizer_resolver()
        return await summarizer.summarize(evaluations)

    @staticmethod
    def _flatten(points: SummarizeInput) -> list[PromptEvaluation]:
        """Flatten a mix of points/evaluations into a flat evaluation list."""

        evaluations: list[PromptEvaluation] = []
        for item in points:
            if isinstance(item, EvaluationPoint):
                evaluations.extend(item.step_evaluations)
            elif isinstance(item, PromptEvaluation):
                evaluations.append(item)
            else:  # pragma: no cover - defensive guard
                raise TypeError(
                    "summarize() expects EvaluationPoint or PromptEvaluation "
                    f"items, got {type(item).__name__}."
                )
        return evaluations
