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

import asyncio
import logging
from collections.abc import Awaitable, Callable

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
from app.services.optimizer import OptimizerService
from app.services.progress import ProgressTracker
from app.services.summarizer import SummarizerService

__all__ = ["execute_evaluation_run", "execute_optimization_run", "cancel_run"]

logger = logging.getLogger(__name__)

# Live background work keyed by run_id, so a stop request can cancel it.
# Single-process registry (runs execute in this process's event loop).
_RUNNING_TASKS: dict[str, asyncio.Task] = {}


def cancel_run(run_id: str) -> bool:
    """Request cancellation of a live background run.

    :returns: ``True`` when a running task was found and told to cancel — its
        wrapper then marks the run ``cancelled`` and emits the terminal
        progress event. ``False`` when no live task exists (already finished,
        or the process restarted); callers should fall back to fixing the
        persisted status themselves.
    """

    task = _RUNNING_TASKS.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def _run_cancellable(
    run_id: str,
    body: Awaitable[None],
    on_cancelled: Callable[[], Awaitable[None]],
) -> None:
    """Await ``body`` as a registered task so :func:`cancel_run` can stop it.

    A user-initiated cancel lands here as the inner task's ``CancelledError``;
    the run is then marked cancelled via ``on_cancelled``. Cancellation of the
    *outer* task (server shutdown) is propagated untouched.
    """

    task = asyncio.ensure_future(body)
    _RUNNING_TASKS[run_id] = task
    try:
        await task
    except asyncio.CancelledError:
        if not task.cancelled():  # outer cancellation, not a user stop
            task.cancel()
            raise
        logger.info("Run %s cancelled by user", run_id)
        try:
            await on_cancelled()
        except Exception:  # noqa: BLE001 - cleanup must not raise
            logger.exception("Failed to mark run %s cancelled", run_id)
    finally:
        _RUNNING_TASKS.pop(run_id, None)


async def _mark_cancelled(
    runs, tracker: ProgressTracker, run_id: str
) -> None:
    """Persist the ``cancelled`` status and publish the terminal event."""

    await runs.update(
        run_id,
        {"status": RunStatus.CANCELLED.value, "error": "Stopped by user."},
    )
    await tracker.publish(
        run_id, {"event": "run_cancelled", "current_step": "cancelled"}
    )


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

    async def _body() -> None:
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
                    db, prompt_id, prompt_text, result
                )
        except Exception as exc:  # noqa: BLE001 - background jobs must not raise
            logger.exception("Standalone evaluation run %s failed", run_id)
            await runs.update(
                run_id, {"status": RunStatus.FAILED.value, "error": str(exc)}
            )
            await _emit_error(tracker, run_id, exc)

    await _run_cancellable(
        run_id, _body(), lambda: _mark_cancelled(runs, tracker, run_id)
    )


async def _apply_evaluation_to_prompt(
    db: AsyncIOMotorDatabase,
    prompt_id: str,
    prompt_text: str,
    result: EvaluationRunResult,
) -> None:
    """Fold a standalone evaluation's outcome into the stored prompt.

    Mirrors the optimizer's baseline behaviour: the evaluated text becomes the
    current prompt (a no-op when it was not overridden), and the measured score
    and summarized strengths/weaknesses/reasoning replace the previous ones.
    The summary uses the LLM runner selected on the prompt.
    """

    prompt_doc = await PromptRepository(db).get(prompt_id) or {}
    summary = await SummarizerService().summarize(
        result.points,
        llm_runner_name=prompt_doc.get("summarizer_llm_runner"),
        llm_runner_options=prompt_doc.get("summarizer_llm_runner_options") or {},
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

    async def _body() -> None:
        try:
            await optimizer.optimize(prompt_id, config, run_id=run_id)
        except Exception:  # noqa: BLE001 - already recorded by the optimizer
            logger.exception("Optimization run %s failed", run_id)

    await _run_cancellable(
        run_id,
        _body(),
        lambda: _mark_cancelled(OptimizationRunRepository(db), tracker, run_id),
    )


async def _emit_error(
    tracker: ProgressTracker, run_id: str, exc: Exception
) -> None:
    """Publish an ``error`` progress event; never raises."""

    try:
        await tracker.publish(run_id, {"event": "error", "error": str(exc)})
    except Exception:  # noqa: BLE001 - progress must never mask the failure
        logger.exception("Failed to publish error event for run %s", run_id)
