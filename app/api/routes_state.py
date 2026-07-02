"""Optimization state management routes (Task 13).

JSON API under ``/api/states``: create/list/get/update/delete
:class:`OptimizationState` documents (goal, current prompt, linked test cases).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_state_repository, get_test_case_repository
from app.db.repositories import OptimizationStateRepository, TestCaseRepository
from app.models import OptimizationState

router = APIRouter(prefix="/api/states", tags=["states"])


class StateCreate(BaseModel):
    """Request payload for creating an optimization state."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(..., min_length=1)
    current_prompt: str = Field(..., min_length=1)
    test_case_ids: list[str] = Field(default_factory=list)


class StateUpdate(BaseModel):
    """Partial update payload; omitted fields are left unchanged."""

    model_config = ConfigDict(extra="forbid")

    goal: Optional[str] = Field(default=None, min_length=1)
    current_prompt: Optional[str] = Field(default=None, min_length=1)
    test_case_ids: Optional[list[str]] = Field(default=None)


async def _validate_test_case_ids(
    ids: list[str], test_cases: TestCaseRepository
) -> None:
    """Reject payloads referencing test cases that do not exist."""

    if not ids:
        return
    found = {doc["id"] for doc in await test_cases.list_by_ids(ids)}
    missing = [tcid for tcid in ids if tcid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown test case ids: {missing}.",
        )


@router.post(
    "", response_model=OptimizationState, status_code=status.HTTP_201_CREATED
)
async def create_state(
    payload: StateCreate,
    repo: OptimizationStateRepository = Depends(get_state_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    await _validate_test_case_ids(payload.test_case_ids, test_cases)
    state = OptimizationState(**payload.model_dump())
    return await repo.create(state.model_dump())


@router.get("", response_model=list[OptimizationState])
async def list_states(
    skip: int = 0,
    limit: int = 100,
    repo: OptimizationStateRepository = Depends(get_state_repository),
) -> Any:
    return await repo.list(skip=skip, limit=limit)


@router.get("/{state_id}", response_model=OptimizationState)
async def get_state(
    state_id: str,
    repo: OptimizationStateRepository = Depends(get_state_repository),
) -> Any:
    doc = await repo.get(state_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State {state_id!r} not found.",
        )
    return doc


@router.put("/{state_id}", response_model=OptimizationState)
async def update_state(
    state_id: str,
    payload: StateUpdate,
    repo: OptimizationStateRepository = Depends(get_state_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    existing = await repo.get(state_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State {state_id!r} not found.",
        )

    changes = payload.model_dump(exclude_none=True)
    if "test_case_ids" in changes:
        await _validate_test_case_ids(changes["test_case_ids"], test_cases)

    # A manually edited prompt invalidates the measured score/summary — the
    # next optimization run re-establishes a baseline (plan §6.2).
    if (
        "current_prompt" in changes
        and changes["current_prompt"] != existing.get("current_prompt")
    ):
        changes.update(
            {"avg_score": None, "strengths": [], "weaknesses": [], "reasoning": ""}
        )

    return await repo.update(state_id, changes)


@router.delete("/{state_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_state(
    state_id: str,
    repo: OptimizationStateRepository = Depends(get_state_repository),
) -> None:
    if not await repo.delete(state_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State {state_id!r} not found.",
        )
