"""Optimization loop routes (Task 13).

JSON API under ``/api/optimizations``:

- ``POST`` — start the feedback loop for a ``state_id`` with a
  :class:`RunConfig`; creates the run (``pending``), schedules the loop via
  BackgroundTasks, and returns the ``run_id`` immediately.
- ``GET /{run_id}`` — run status + persisted progress.
- ``GET /{run_id}/steps`` — the run's :class:`OptimizationStep` documents.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, ConfigDict, Field

from app.api.background import execute_optimization_run
from app.api.deps import (
    get_optimization_run_repository,
    get_state_repository,
    get_step_repository,
)
from app.api.routes_evaluation import RunStartedResponse
from app.db.repositories import (
    OptimizationRunRepository,
    OptimizationStateRepository,
    OptimizationStepRepository,
)
from app.models import OptimizationRun, RunConfig, RunStatus

router = APIRouter(prefix="/api/optimizations", tags=["optimizations"])


class OptimizationStartRequest(BaseModel):
    """Start an optimization loop for a stored state."""

    model_config = ConfigDict(extra="forbid")

    state_id: str = Field(..., min_length=1)
    config: RunConfig = Field(default_factory=RunConfig)


@router.post(
    "", response_model=RunStartedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def start_optimization(
    payload: OptimizationStartRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    states: OptimizationStateRepository = Depends(get_state_repository),
) -> Any:
    state = await states.get(payload.state_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"State {payload.state_id!r} not found.",
        )
    if not state.get("test_case_ids"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"State {payload.state_id!r} has no linked test cases; "
            "add test cases before optimizing.",
        )

    run = OptimizationRun(
        state_id=payload.state_id,
        config=payload.config,
        status=RunStatus.PENDING,
    )
    await runs.create(run.model_dump())

    background_tasks.add_task(
        execute_optimization_run,
        request.app.state.db,
        request.app.state.progress_tracker,
        run.id,
        payload.state_id,
        payload.config,
    )
    return RunStartedResponse(run_id=run.id)


@router.get("", response_model=list[dict])
async def list_optimizations(
    skip: int = 0,
    limit: int = 100,
    runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
) -> Any:
    return await runs.list(skip=skip, limit=limit)


@router.get("/{run_id}", response_model=dict)
async def get_optimization(
    run_id: str,
    runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
) -> Any:
    doc = await runs.get(run_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization run {run_id!r} not found.",
        )
    return doc


@router.get("/{run_id}/steps", response_model=list[dict])
async def list_optimization_steps(
    run_id: str,
    runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    steps: OptimizationStepRepository = Depends(get_step_repository),
) -> Any:
    if await runs.get(run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization run {run_id!r} not found.",
        )
    return await steps.list_by_run(run_id)
