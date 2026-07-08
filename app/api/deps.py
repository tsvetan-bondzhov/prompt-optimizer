"""FastAPI dependency providers (Task 12).

Routes never construct repositories/services themselves — they declare these
providers with ``Depends(...)``. Everything is derived from the two shared
singletons stored on ``app.state`` by the lifespan handler (Task 12 /
:mod:`app.main`):

  - ``app.state.db`` — the Motor database handle (a mongomock-motor database in
    tests, injected through ``create_app(database=...)``).
  - ``app.state.progress_tracker`` — the process-wide :class:`ProgressTracker`.

Repositories are cheap stateless wrappers around the database handle, so they
are constructed per-request rather than cached.
"""

from __future__ import annotations

from fastapi import Depends, Request
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
from app.services.evaluator import EvaluatorService
from app.services.optimizer import OptimizerService
from app.services.progress import ProgressTracker
from app.services.summarizer import SummarizerService

__all__ = [
    "get_db",
    "get_progress_tracker",
    "get_test_case_repository",
    "get_prompt_repository",
    "get_prompt_version_repository",
    "get_optimization_run_repository",
    "get_step_repository",
    "get_evaluation_run_repository",
    "get_report_repository",
    "get_evaluator_service",
    "get_summarizer_service",
    "get_optimizer_service",
]


# -- shared singletons (from app.state) -------------------------------------


def get_db(request: Request) -> AsyncIOMotorDatabase:
    """The Motor database handle stored on ``app.state`` by the lifespan."""

    return request.app.state.db


def get_progress_tracker(request: Request) -> ProgressTracker:
    """The process-wide progress tracker (one instance per application)."""

    return request.app.state.progress_tracker


# -- repositories -------------------------------------------------------------


def get_test_case_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TestCaseRepository:
    return TestCaseRepository(db)


def get_prompt_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> PromptRepository:
    return PromptRepository(db)


def get_prompt_version_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> PromptVersionRepository:
    return PromptVersionRepository(db)


def get_optimization_run_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> OptimizationRunRepository:
    return OptimizationRunRepository(db)


def get_step_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> OptimizationStepRepository:
    return OptimizationStepRepository(db)


def get_evaluation_run_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> EvaluationRunRepository:
    return EvaluationRunRepository(db)


def get_report_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> EvaluationReportRepository:
    return EvaluationReportRepository(db)


# -- services -----------------------------------------------------------------


def get_evaluator_service(
    reports: EvaluationReportRepository = Depends(get_report_repository),
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> EvaluatorService:
    return EvaluatorService(reports, runs)


def get_summarizer_service() -> SummarizerService:
    return SummarizerService()


def get_optimizer_service(
    evaluator: EvaluatorService = Depends(get_evaluator_service),
    summarizer: SummarizerService = Depends(get_summarizer_service),
    states: PromptRepository = Depends(get_prompt_repository),
    runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    steps: OptimizationStepRepository = Depends(get_step_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
    reports: EvaluationReportRepository = Depends(get_report_repository),
    versions: PromptVersionRepository = Depends(get_prompt_version_repository),
    tracker: ProgressTracker = Depends(get_progress_tracker),
) -> OptimizerService:
    return OptimizerService(
        evaluator,
        summarizer,
        states,
        runs,
        steps,
        test_cases,
        report_repository=reports,
        version_repository=versions,
        progress=tracker,
    )
