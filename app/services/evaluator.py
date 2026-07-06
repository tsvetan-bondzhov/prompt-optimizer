"""Prompt Evaluator service (Task 08).

The :class:`EvaluatorService` runs a single prompt against a set of test cases,
``executions_per_test_case`` times each, applies the ordered user-supplied
graders to every produced result, aggregates the per-grader scores into a
single point score, and persists one :class:`EvaluationReport` per evaluation
point (linked to an owning :class:`EvaluationRun`).

It is fully decoupled from the optimizer: it can be called standalone (the run
it creates is itself a viewable evaluation run) or driven by the optimization
loop (which supplies its own ``run_id``).

Implementations (executor, graders, aggregator) are resolved through
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
    Grader,
    LLMRunner,
    PromptExecutor,
)
from app.core.registry import (
    get_aggregator,
    get_executor,
    get_grader,
    get_llm_runner,
)
from app.db.repositories.reports import (
    EvaluationReportRepository,
    EvaluationRunRepository,
)
from app.models import (
    DataEntryResult,
    EvaluationPoint,
    EvaluationReport,
    EvaluationRun,
    PromptText,
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
ExecutorResolver = Callable[[str], PromptExecutor]  # name -> executor
GraderResolver = Callable[[str], Grader]  # name -> Grader instance
LLMRunnerResolver = Callable[[str], LLMRunner]  # name -> runner
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
        grader_resolver: GraderResolver = get_grader,
        llm_runner_resolver: LLMRunnerResolver = get_llm_runner,
        aggregator_resolver: AggregatorResolver = get_aggregator,
    ) -> None:
        """:param report_repository: Persists one report per evaluation point.
        :param run_repository: Persists/updates the grouping evaluation run.
        :param executor_resolver: Resolves an executor name to an instance;
            each test case selects its executor via ``executor_name``.
        :param grader_resolver: Resolves a grader name to an instance; each
            test case selects its graders via ``grader_names``.
        :param llm_runner_resolver: Resolves an LLM runner name to an instance
            (used for the test case's ``executor_llm_runner``).
        :param aggregator_resolver: Returns the per-point score aggregator.
        """

        self._reports = report_repository
        self._runs = run_repository
        self._executor_resolver = executor_resolver
        self._grader_resolver = grader_resolver
        self._llm_runner_resolver = llm_runner_resolver
        self._aggregator_resolver = aggregator_resolver

    async def run(
        self,
        prompt: PromptText,
        test_cases: Sequence[TestCase],
        executions_per_test_case: int,
        run_id: Optional[str] = None,
        progress: Optional[ProgressHook] = None,
        prompt_name: Optional[str] = None,
    ) -> EvaluationRunResult:
        """Evaluate ``prompt`` over ``test_cases`` × ``executions_per_test_case``.

        For every ``(test_case, execution_index)`` pair the active executor runs
        the prompt, the ordered graders score the result, the per-grader
        scores are aggregated into a single point score, and an
        :class:`EvaluationReport` is persisted (linked to the owning run).

        :param prompt: The prompt under evaluation.
        :param test_cases: Non-empty sequence of test cases to evaluate against.
        :param executions_per_test_case: Executions per test case (``>= 1``).
        :param run_id: Existing run id to link reports to. When ``None`` a new
            standalone :class:`EvaluationRun` is created and used.
        :param progress: Optional hook invoked with progress event dicts.
        :param prompt_name: Name of the stored prompt being evaluated (if any);
            persisted on the run and every report for display.
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

        aggregator = self._aggregator_resolver()

        # Resolve each test case's executor, LLM runner, and selected graders
        # up front (fail fast on an empty selection or an unknown name).
        executors_by_case: dict[str, PromptExecutor] = {}
        runners_by_case: dict[str, LLMRunner] = {}
        graders_by_case: dict[str, list[Grader]] = {}
        for test_case in test_cases:
            if not test_case.grader_names:
                raise ValueError(
                    f"Test case {test_case.name!r} has no graders selected."
                )
            executors_by_case[test_case.id] = self._executor_resolver(
                test_case.executor_name
            )
            runners_by_case[test_case.id] = self._llm_runner_resolver(
                test_case.executor_llm_runner
            )
            graders_by_case[test_case.id] = [
                self._grader_resolver(name) for name in test_case.grader_names
            ]

        total = executions_per_test_case * len(test_cases)

        # Create a standalone owning run unless one was supplied by the caller
        # (e.g. the optimizer manages its own run lifecycle).
        owns_run = run_id is None
        if owns_run:
            run_doc = await self._runs.create(
                EvaluationRun(
                    prompt=prompt.text,
                    prompt_name=prompt_name,
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
                        prompt_name=prompt_name,
                        test_case=test_case,
                        execution_index=execution_index,
                        executor=executors_by_case[test_case.id],
                        llm_runner=runners_by_case[test_case.id],
                        graders=graders_by_case[test_case.id],
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
        prompt: PromptText,
        prompt_name: Optional[str],
        test_case: TestCase,
        execution_index: int,
        executor: PromptExecutor,
        llm_runner: LLMRunner,
        graders: list[Grader],
        aggregator: Aggregator,
        run_id: Optional[str],
    ) -> tuple[EvaluationPoint, str, Optional[str]]:
        """Run one evaluation point, persist its report, and return both.

        Every data entry of the test case is executed and graded individually;
        the point score is the mean of the per-entry scores. Robustness: a
        failure while executing/grading an entry is captured as a *failed*
        entry (score ``1``) rather than aborting the run. The returned error
        string (or ``None``) is surfaced in progress events.
        """

        entries = test_case.data or [{}]
        entry_results: list[DataEntryResult] = []
        errors: list[str] = []

        for entry_index, entry in enumerate(entries):
            try:
                result = await executor.execute(
                    prompt, test_case, entry, llm_runner
                )
                if result.prompt_text is None:
                    result = result.model_copy(
                        update={"prompt_text": prompt.text}
                    )
                grader_evals = await self._run_graders(
                    graders, result, test_case, entry_index
                )
                entry_score = (
                    float(aggregator(grader_evals)) if grader_evals else 0.0
                )
                entry_results.append(
                    DataEntryResult(
                        entry_index=entry_index,
                        prompt_result=result.text,
                        grader_evaluations=grader_evals,
                        score=_clamp_score(entry_score),
                    )
                )
            except Exception as exc:  # one bad entry must not abort the run
                logger.exception(
                    "Evaluation entry failed (test_case=%s, i=%s, entry=%s)",
                    test_case.id,
                    execution_index,
                    entry_index,
                )
                errors.append(f"entry {entry_index}: {exc}")
                entry_results.append(
                    DataEntryResult(
                        entry_index=entry_index,
                        prompt_result="",
                        grader_evaluations=[],
                        score=1.0,
                    )
                )

        error: Optional[str] = "; ".join(errors) if errors else None
        aggregated_score = _clamp_score(
            sum(er.score for er in entry_results) / len(entry_results)
        )
        grader_evals = [
            evaluation
            for er in entry_results
            for evaluation in er.grader_evaluations
        ]
        result_text = "\n\n".join(
            er.prompt_result for er in entry_results if er.prompt_result
        )

        merged = _merge_evaluations(grader_evals, error=error)

        report = EvaluationReport(
            run_id=run_id,
            test_case_id=test_case.id,
            prompt=prompt.text,
            prompt_name=prompt_name,
            prompt_result=result_text,
            score=aggregated_score,
            strengths=merged["strengths"],
            weaknesses=merged["weaknesses"],
            reasoning=merged["reasoning"],
            grader_evaluations=grader_evals,
            entry_results=entry_results,
        )
        stored = await self._reports.create(report.model_dump())
        report_id = stored.get("id", report.id)

        point = EvaluationPoint(
            test_case_id=test_case.id,
            execution_index=execution_index,
            prompt_result=result_text,
            entry_results=entry_results,
            grader_evaluations=grader_evals,
            aggregated_score=aggregated_score,
        )
        return point, report_id, error

    async def _run_graders(
        self,
        graders: list[Grader],
        result: PromptResult,
        test_case: TestCase,
        entry_index: int,
    ) -> list[PromptEvaluation]:
        """Run the ordered graders sequentially, tagging each with its name."""

        evaluations: list[PromptEvaluation] = []
        for grader in graders:
            evaluation = await grader.grade(result, test_case, entry_index)
            if evaluation.grader_name is None:
                evaluation = evaluation.model_copy(
                    update={"grader_name": getattr(grader, "name", None)}
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
    grader_evals: list[PromptEvaluation], *, error: Optional[str] = None
) -> dict[str, Any]:
    """Merge per-grader strengths/weaknesses/reasoning for the persisted report.

    Strengths and weaknesses are de-duplicated while preserving order; reasoning
    is a readable concatenation prefixed by each step's name. A captured
    ``error`` is surfaced as a weakness and in the reasoning so failed points
    remain inspectable.
    """

    strengths: list[str] = []
    weaknesses: list[str] = []
    reasoning_parts: list[str] = []

    for evaluation in grader_evals:
        label = evaluation.grader_name or "step"
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
