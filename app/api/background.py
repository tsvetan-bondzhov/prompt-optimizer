"""Background run execution helpers (Task 12).

Routes that start a long-running job follow the same pattern:

  1. Create the run document with status ``pending`` and return its ``run_id``
     immediately (so the UI can redirect to the progress page).
  2. Schedule one of the coroutines below via FastAPI ``BackgroundTasks``.
     Starlette awaits background coroutines on the running event loop after the
     response is sent, so the async services execute normally.
  3. The coroutine moves the run to ``running``, executes the service with the
     shared :class:`ProgressTracker` attached, and marks the run ``completed``
     or ``failed`` — exceptions are always caught, recorded on the run document,
     and surfaced as an ``error`` progress event.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
    OptimizationRunRepository,
    PromptRepository,
    PromptVersionRepository,
    OptimizationStepRepository,
    TestCaseRepository,
)
from app.models import PromptText, RunConfig, RunStatus, TestCase
from app.services.evaluator import EvaluationRunResult, EvaluatorService
from app.services.optimizer import OptimizerService, summarizer_runner_selection
from app.services.progress import ProgressTracker
from app.services.summarizer import SummarizerService

__all__ = ["execute_evaluation_run", "execute_optimization_run"]

logger = logging.getLogger(__name__)


async def execute_evaluation_run(
    db: AsyncIOMotorDatabase,
    tracker: ProgressTracker,
    run_id: str,
    prompt_text: str,
    test_cases: list[TestCase],
    executions_per_test_case: int,
    prompt_name: str | None = None,
    prompt_id: str | None = None,
    update_prompt: bool = False,
) -> None:
    """Execute a standalone evaluation for a pre-created (``pending``) run.

    The route has already created the ``EvaluationRun`` document; this coroutine
    owns its status transitions from here on (the evaluator itself leaves runs
    it did not create untouched).

    When ``update_prompt`` is true (requires ``prompt_id``), the stored prompt
    is updated from this run after completion: measured ``avg_score`` plus the
    summarized strengths/weaknesses/reasoning — and the evaluated text becomes
    the prompt's ``current_prompt`` when it was overridden in the form.
    """

    runs = EvaluationRunRepository(db)
    evaluator = EvaluatorService(EvaluationReportRepository(db), runs)

    try:
        await runs.update(run_id, {"status": RunStatus.RUNNING.value})
        result = await evaluator.run(
            PromptText(text=prompt_text),
            test_cases,
            executions_per_test_case,
            run_id=run_id,
            progress=tracker.make_hook(run_id),
            prompt_name=prompt_name,
        )
        await runs.update(
            run_id,
            {
                "status": RunStatus.COMPLETED.value,
                "avg_score": result.avg_score,
                "metadata": {"report_ids": result.report_ids},
            },
        )
        if update_prompt and prompt_id is not None:
            await _apply_evaluation_to_prompt(
                db, prompt_id, prompt_text, test_cases, result
            )
    except Exception as exc:  # noqa: BLE001 - background jobs must not raise
        logger.exception("Standalone evaluation run %s failed", run_id)
        await runs.update(
            run_id, {"status": RunStatus.FAILED.value, "error": str(exc)}
        )
        await _emit_error(tracker, run_id, exc)


async def _apply_evaluation_to_prompt(
    db: AsyncIOMotorDatabase,
    prompt_id: str,
    prompt_text: str,
    test_cases: list[TestCase],
    result: EvaluationRunResult,
) -> None:
    """Fold a standalone evaluation's outcome into the stored prompt.

    Mirrors the optimizer's baseline behaviour: the evaluated text becomes the
    current prompt (a no-op when it was not overridden), and the measured score
    and summarized strengths/weaknesses/reasoning replace the previous ones.
    """

    runner_name, runner_options = summarizer_runner_selection(test_cases)
    summary = await SummarizerService().summarize(
        result.points,
        llm_runner_name=runner_name,
        llm_runner_options=runner_options,
    )
    await PromptRepository(db).update(
        prompt_id,
        {
            "current_prompt": prompt_text,
            "avg_score": result.avg_score,
            "strengths": summary.strengths,
            "weaknesses": summary.weaknesses,
            "reasoning": summary.reasoning,
        },
    )


async def execute_optimization_run(
    db: AsyncIOMotorDatabase,
    tracker: ProgressTracker,
    run_id: str,
    prompt_id: str,
    config: RunConfig,
) -> None:
    """Execute the optimization loop for a pre-created (``pending``) run.

    :class:`OptimizerService` manages the run's status transitions and error
    events itself; this wrapper only guarantees the exception never escapes the
    background task (the run is already marked ``failed`` by the service).
    """

    optimizer = OptimizerService(
        EvaluatorService(
            EvaluationReportRepository(db), EvaluationRunRepository(db)
        ),
        SummarizerService(),
        PromptRepository(db),
        OptimizationRunRepository(db),
        OptimizationStepRepository(db),
        TestCaseRepository(db),
        report_repository=EvaluationReportRepository(db),
        version_repository=PromptVersionRepository(db),
        progress=tracker,
    )

    try:
        await optimizer.optimize(prompt_id, config, run_id=run_id)
    except Exception:  # noqa: BLE001 - already recorded by the optimizer
        logger.exception("Optimization run %s failed", run_id)


async def _emit_error(
    tracker: ProgressTracker, run_id: str, exc: Exception
) -> None:
    """Publish an ``error`` progress event; never raises."""

    try:
        await tracker.publish(run_id, {"event": "error", "error": str(exc)})
    except Exception:  # noqa: BLE001 - progress must never mask the failure
        logger.exception("Failed to publish error event for run %s", run_id)
