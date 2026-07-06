"""Prompt management routes (Task 13).

JSON API under ``/api/prompts``: create/list/get/update/delete
:class:`Prompt` documents (name, goal, current prompt, linked test cases).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_prompt_repository, get_test_case_repository
from app.db.repositories import PromptRepository, TestCaseRepository
from app.models import Prompt

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    """Request payload for creating a prompt."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    goal: str = Field(..., min_length=1)
    current_prompt: str = Field(..., min_length=1)
    test_case_ids: list[str] = Field(default_factory=list)
    optimizer_llm_runner: Optional[str] = Field(default=None, min_length=1)
    optimizer_llm_runner_options: Optional[dict] = Field(default=None)


class PromptUpdate(BaseModel):
    """Partial update payload; omitted fields are left unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1)
    goal: Optional[str] = Field(default=None, min_length=1)
    current_prompt: Optional[str] = Field(default=None, min_length=1)
    test_case_ids: Optional[list[str]] = Field(default=None)
    optimizer_llm_runner: Optional[str] = Field(default=None, min_length=1)
    optimizer_llm_runner_options: Optional[dict] = Field(default=None)


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
    "", response_model=Prompt, status_code=status.HTTP_201_CREATED
)
async def create_prompt(
    payload: PromptCreate,
    repo: PromptRepository = Depends(get_prompt_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    await _validate_test_case_ids(payload.test_case_ids, test_cases)
    prompt = Prompt(**payload.model_dump(exclude_none=True))
    return await repo.create(prompt.model_dump())


@router.get("", response_model=list[Prompt])
async def list_prompts(
    skip: int = 0,
    limit: int = 100,
    repo: PromptRepository = Depends(get_prompt_repository),
) -> Any:
    return await repo.list(skip=skip, limit=limit)


@router.get("/{prompt_id}", response_model=Prompt)
async def get_prompt(
    prompt_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
) -> Any:
    doc = await repo.get(prompt_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt {prompt_id!r} not found.",
        )
    return doc


@router.put("/{prompt_id}", response_model=Prompt)
async def update_prompt(
    prompt_id: str,
    payload: PromptUpdate,
    repo: PromptRepository = Depends(get_prompt_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    existing = await repo.get(prompt_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt {prompt_id!r} not found.",
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

    return await repo.update(prompt_id, changes)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    prompt_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
) -> None:
    if not await repo.delete(prompt_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt {prompt_id!r} not found.",
        )
