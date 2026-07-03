"""Standalone evaluation routes (Task 13).

JSON API under ``/api/evaluations``:

- ``POST`` — start a standalone evaluation (prompt + test cases + N); creates
  the run document (``pending``), schedules the work via BackgroundTasks, and
  returns the ``run_id`` immediately.
- ``GET /{run_id}`` — run status + summary.
- ``GET /{run_id}/reports`` — the run's evaluation reports.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.background import execute_evaluation_run
from app.api.deps import (
    get_evaluation_run_repository,
    get_report_repository,
    get_prompt_repository,
    get_test_case_repository,
)
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
    PromptRepository,
    TestCaseRepository,
)
from app.models import EvaluationRun, RunStatus, TestCase

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


class EvaluationStartRequest(BaseModel):
    """Start a standalone evaluation.

    The prompt comes either from ``prompt`` (explicit text) or from the current
    prompt of the stored prompt referenced by ``prompt_id``. Test cases likewise: an
    explicit ``test_case_ids`` selection, or the stored prompt's linked test cases.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: Optional[str] = Field(default=None, min_length=1)
    prompt_id: Optional[str] = Field(default=None)
    test_case_ids: list[str] = Field(default_factory=list)
    executions_per_test_case: int = Field(default=1, ge=1)


class RunStartedResponse(BaseModel):
    """Returned immediately when a background run is scheduled."""

    run_id: str
    status: str = RunStatus.PENDING.value


async def resolve_test_cases(
    ids: list[str], repo: TestCaseRepository
) -> list[TestCase]:
    """Load and validate the selected test cases (order preserved)."""

    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one test case is required.",
        )
    docs = await repo.list_by_ids(ids)
    by_id = {doc["id"]: doc for doc in docs}
    missing = [tcid for tcid in ids if tcid not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown test case ids: {missing}.",
        )
    return [TestCase.model_validate(by_id[tcid]) for tcid in ids]


@router.post(
    "", response_model=RunStartedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def start_evaluation(
    payload: EvaluationStartRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    test_case_repo: TestCaseRepository = Depends(get_test_case_repository),
    prompts: PromptRepository = Depends(get_prompt_repository),
) -> Any:
    prompt_text = payload.prompt
    prompt_name: str | None = None
    test_case_ids = list(payload.test_case_ids)

    if payload.prompt_id is not None:
        prompt_doc = await prompts.get(payload.prompt_id)
        if prompt_doc is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Prompt {payload.prompt_id!r} not found.",
            )
        prompt_name = prompt_doc.get("name")
        if prompt_text is None:
            prompt_text = prompt_doc.get("current_prompt")
        if not test_case_ids:
            test_case_ids = list(prompt_doc.get("test_case_ids") or [])

    if not prompt_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A prompt is required (either 'prompt' or a 'prompt_id' "
            "whose prompt has a current prompt text).",
        )

    test_cases = await resolve_test_cases(test_case_ids, test_case_repo)

    run = EvaluationRun(
        prompt=prompt_text,
        prompt_name=prompt_name,
        test_case_ids=[tc.id for tc in test_cases],
        executions_per_test_case=payload.executions_per_test_case,
        status=RunStatus.PENDING.value,
    )
    await runs.create(run.model_dump())

    background_tasks.add_task(
        execute_evaluation_run,
        request.app.state.db,
        request.app.state.progress_tracker,
        run.id,
        prompt_text,
        test_cases,
        payload.executions_per_test_case,
        prompt_name,
    )
    return RunStartedResponse(run_id=run.id)


@router.get("", response_model=list[dict])
async def list_evaluations(
    skip: int = 0,
    limit: int = 100,
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> Any:
    return await runs.list(skip=skip, limit=limit)


@router.get("/{run_id}", response_model=dict)
async def get_evaluation(
    run_id: str,
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> Any:
    doc = await runs.get(run_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation run {run_id!r} not found.",
        )
    return doc


@router.get("/{run_id}/reports", response_model=list[dict])
async def list_evaluation_reports(
    run_id: str,
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    reports: EvaluationReportRepository = Depends(get_report_repository),
) -> Any:
    if await runs.get(run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation run {run_id!r} not found.",
        )
    return await reports.list_by_run(run_id)
