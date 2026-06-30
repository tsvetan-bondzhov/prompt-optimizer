"""Prompt Evaluator service (Task 08).

The :class:`EvaluatorService` runs a single prompt against a set of test cases,
``executions_per_test_case`` times each, applies the ordered user-supplied
evaluation steps to every produced result, aggregates the per-step scores into a
single point score, and persists one :class:`EvaluationReport` per evaluation
point (linked to an owning :class:`EvaluationRun`).

It is fully decoupled from the optimizer: it can be called standalone (the run
it creates is itself a viewable evaluation run) or driven by the optimization
loop (which supplies its own ``run_id``).

Implementations (executor, evaluation steps, aggregator) are resolved through
:mod:`app.core.registry`; nothing is hardcoded. The optional ``progress``
callback is a minimal seam for the real ``ProgressTracker`` built in Task 11.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.interfaces import (
    Aggregator,
    EvaluationStep,
    PromptExecutor,
)
from app.core.registry import (
    get_aggregator,
    get_evaluation_steps,
    get_executor,
)
from app.db.repositories.reports import (
    EvaluationReportRepository,
    EvaluationRunRepository,
)
from app.models import (
    EvaluationPoint,
    EvaluationReport,
    EvaluationRun,
    Prompt,
    PromptEvaluation,
    PromptResult,
    TestCase,
)

__all__ = ["EvaluationRunResult", "EvaluatorService"]

logger = logging.getLogger(__name__)

# A progress hook is any callable invoked with a single event dict. It may be a
# plain function or a coroutine function; both are supported. The real
# ProgressTracker (Task 11) can adapt to this shape.
ProgressHook = Callable[[dict[str, Any]], Optional[Awaitable[None]]]

# Resolver callables (default to the registry helpers, overridable for tests).
ExecutorResolver = Callable[[], PromptExecutor]
StepsResolver = Callable[[], list[EvaluationStep]]
AggregatorResolver = Callable[[], Aggregator]


class EvaluationRunResult(BaseModel):
    """In-memory result of a single :meth:`EvaluatorService.run` invocation.

    Holds every produced :class:`EvaluationPoint`, the ids of the persisted
    :class:`EvaluationReport` documents (one per point, same order), the owning
    ``run_id``, and the mean aggregated score across all points.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: Optional[str] = Field(
        default=None, description="Owning EvaluationRun id (if any)."
    )
    points: list[EvaluationPoint] = Field(default_factory=list)
    report_ids: list[str] = Field(default_factory=list)
    avg_score: float = Field(default=0.0, description="Mean of point scores.")


class EvaluatorService:
    """Evaluate a prompt across test cases and persist the resulting reports."""

    def __init__(
        self,
        report_repository: EvaluationReportRepository,
        run_repository: EvaluationRunRepository,
        *,
        executor_resolver: ExecutorResolver = get_executor,
        steps_resolver: StepsResolver = get_evaluation_steps,
        aggregator_resolver: AggregatorResolver = get_aggregator,
    ) -> None:
        """:param report_repository: Persists one report per evaluation point.
        :param run_repository: Persists/updates the grouping evaluation run.
        :param executor_resolver: Returns the active :class:`PromptExecutor`.
        :param steps_resolver: Returns the ordered evaluation steps to run.
        :param aggregator_resolver: Returns the per-point score aggregator.
        """

        self._reports = report_repository
        self._runs = run_repository
        self._executor_resolver = executor_resolver
        self._steps_resolver = steps_resolver
        self._aggregator_resolver = aggregator_resolver

    async def run(
        self,
        prompt: Prompt,
        test_cases: Sequence[TestCase],
        executions_per_test_case: int,
        run_id: Optional[str] = None,
        progress: Optional[ProgressHook] = None,
    ) -> EvaluationRunResult:
        """Evaluate ``prompt`` over ``test_cases`` × ``executions_per_test_case``.

        For every ``(test_case, execution_index)`` pair the active executor runs
        the prompt, the ordered evaluation steps score the result, the per-step
        scores are aggregated into a single point score, and an
        :class:`EvaluationReport` is persisted (linked to the owning run).

        :param prompt: The prompt under evaluation.
        :param test_cases: Non-empty sequence of test cases to evaluate against.
        :param executions_per_test_case: Executions per test case (``>= 1``).
        :param run_id: Existing run id to link reports to. When ``None`` a new
            standalone :class:`EvaluationRun` is created and used.
        :param progress: Optional hook invoked with progress event dicts.
        :returns: An :class:`EvaluationRunResult` with all points, report ids,
            and the mean point score.
        :raises ValueError: If ``test_cases`` is empty or ``N < 1``.
        """

        test_cases = list(test_cases)
        if not test_cases:
            raise ValueError("test_cases must not be empty.")
        if executions_per_test_case < 1:
            raise ValueError(
                "executions_per_test_case must be >= 1 "
                f"(got {executions_per_test_case})."
            )

        executor = self._executor_resolver()
        steps = self._steps_resolver()
        aggregator = self._aggregator_resolver()

        total = executions_per_test_case * len(test_cases)

        # Create a standalone owning run unless one was supplied by the caller
        # (e.g. the optimizer manages its own run lifecycle).
        owns_run = run_id is None
        if owns_run:
            run_doc = await self._runs.create(
                EvaluationRun(
                    prompt=prompt.text,
                    test_case_ids=[tc.id for tc in test_cases],
                    executions_per_test_case=executions_per_test_case,
                    status="running",
                ).model_dump()
            )
            run_id = run_doc["id"]

        points: list[EvaluationPoint] = []
        report_ids: list[str] = []
        executed = 0

        try:
            for test_case in test_cases:
                for execution_index in range(executions_per_test_case):
                    point, report_id, error = await self._evaluate_point(
                        prompt=prompt,
                        test_case=test_case,
                        execution_index=execution_index,
                        executor=executor,
                        steps=steps,
                        aggregator=aggregator,
                        run_id=run_id,
                    )
                    points.append(point)
                    report_ids.append(report_id)
                    executed += 1

                    await self._emit(
                        progress,
                        {
                            "event": "executed",
                            "executed": executed,
                            "total": total,
                            "run_id": run_id,
                            "test_case_id": test_case.id,
                            "execution_index": execution_index,
                            "score": point.aggregated_score,
                            "error": error,
                        },
                    )
        except Exception as exc:  # pragma: no cover - defensive
            if owns_run:
                await self._runs.update(run_id, {"status": "failed"})
            await self._emit(
                progress,
                {
                    "event": "error",
                    "executed": executed,
                    "total": total,
                    "run_id": run_id,
                    "error": str(exc),
                },
            )
            raise

        avg_score = (
            sum(p.aggregated_score for p in points) / len(points) if points else 0.0
        )

        if owns_run:
            await self._runs.update(
                run_id,
                {
                    "status": "completed",
                    "avg_score": avg_score,
                    "metadata": {"report_ids": report_ids},
                },
            )

        await self._emit(
            progress,
            {
                "event": "completed",
                "executed": executed,
                "total": total,
                "run_id": run_id,
                "avg_score": avg_score,
            },
        )

        return EvaluationRunResult(
            run_id=run_id,
            points=points,
            report_ids=report_ids,
            avg_score=avg_score,
        )

    async def _evaluate_point(
        self,
        *,
        prompt: Prompt,
        test_case: TestCase,
        execution_index: int,
        executor: PromptExecutor,
        steps: list[EvaluationStep],
        aggregator: Aggregator,
        run_id: Optional[str],
    ) -> tuple[EvaluationPoint, str, Optional[str]]:
        """Run one evaluation point, persist its report, and return both.

        Robustness: a failure in the executor or any step is captured as a
        recorded *failed* report (score ``1``) rather than aborting the run. The
        returned error string (or ``None``) is surfaced in progress events.
        """

        error: Optional[str] = None
        try:
            result = await executor.execute(prompt, test_case)
            step_evals = await self._run_steps(steps, result, test_case)
            point_score = float(aggregator(step_evals)) if step_evals else 0.0
            # Aggregated point score must satisfy EvaluationPoint's [1, 10] bound.
            aggregated_score = _clamp_score(point_score)
            result_text = result.text
        except Exception as exc:  # one bad point must not abort the whole run
            logger.exception(
                "Evaluation point failed (test_case=%s, i=%s)",
                test_case.id,
                execution_index,
            )
            error = str(exc)
            step_evals = []
            aggregated_score = 1.0
            result_text = ""

        merged = _merge_evaluations(step_evals, error=error)

        report = EvaluationReport(
            run_id=run_id,
            test_case_id=test_case.id,
            prompt=prompt.text,
            prompt_result=result_text,
            score=aggregated_score,
            strengths=merged["strengths"],
            weaknesses=merged["weaknesses"],
            reasoning=merged["reasoning"],
            step_evaluations=step_evals,
        )
        stored = await self._reports.create(report.model_dump())
        report_id = stored.get("id", report.id)

        point = EvaluationPoint(
            test_case_id=test_case.id,
            execution_index=execution_index,
            prompt_result=result_text,
            step_evaluations=step_evals,
            aggregated_score=aggregated_score,
        )
        return point, report_id, error

    async def _run_steps(
        self,
        steps: list[EvaluationStep],
        result: PromptResult,
        test_case: TestCase,
    ) -> list[PromptEvaluation]:
        """Run the ordered steps sequentially, tagging each with its step name."""

        evaluations: list[PromptEvaluation] = []
        for step in steps:
            evaluation = await step.evaluate(result, test_case)
            if evaluation.step_name is None:
                evaluation = evaluation.model_copy(
                    update={"step_name": getattr(step, "name", None)}
                )
            evaluations.append(evaluation)
        return evaluations

    @staticmethod
    async def _emit(
        progress: Optional[ProgressHook], event: dict[str, Any]
    ) -> None:
        """Invoke the optional progress hook, supporting sync or async callables."""

        if progress is None:
            return
        try:
            outcome = progress(event)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception:  # progress must never break the evaluation
            logger.exception("Progress hook raised; continuing.")


def _clamp_score(value: float) -> float:
    """Clamp an aggregated point score into the valid ``[1, 10]`` range."""

    return max(1.0, min(10.0, float(value)))


def _merge_evaluations(
    step_evals: list[PromptEvaluation], *, error: Optional[str] = None
) -> dict[str, Any]:
    """Merge per-step strengths/weaknesses/reasoning for the persisted report.

    Strengths and weaknesses are de-duplicated while preserving order; reasoning
    is a readable concatenation prefixed by each step's name. A captured
    ``error`` is surfaced as a weakness and in the reasoning so failed points
    remain inspectable.
    """

    strengths: list[str] = []
    weaknesses: list[str] = []
    reasoning_parts: list[str] = []

    for evaluation in step_evals:
        label = evaluation.step_name or "step"
        for item in evaluation.strengths:
            if item not in strengths:
                strengths.append(item)
        for item in evaluation.weaknesses:
            if item not in weaknesses:
                weaknesses.append(item)
        reasoning_parts.append(f"[{label}] {evaluation.reasoning}")

    if error is not None:
        failure = f"Evaluation failed: {error}"
        if failure not in weaknesses:
            weaknesses.append(failure)
        reasoning_parts.append(failure)

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "reasoning": "\n".join(reasoning_parts),
    }
