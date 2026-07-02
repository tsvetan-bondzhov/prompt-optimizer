"""Test case CRUD routes (Task 13).

JSON API under ``/api/test-cases``: create, bulk import, list, get, update,
delete. Bodies are validated against :class:`TestCaseCreate` (``name`` +
``data`` + ``evaluation_criteria``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_test_case_repository
from app.db.repositories import TestCaseRepository
from app.models import TestCase, TestCaseCreate

router = APIRouter(prefix="/api/test-cases", tags=["test-cases"])


@router.post("", response_model=TestCase, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    payload: TestCaseCreate,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    test_case = TestCase(**payload.model_dump())
    return await repo.create(test_case.model_dump())


@router.post(
    "/import",
    response_model=list[TestCase],
    status_code=status.HTTP_201_CREATED,
)
async def import_test_cases(
    payload: list[TestCaseCreate],
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    """Bulk JSON import: a list of test case payloads, created in order."""

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import payload must contain at least one test case.",
        )
    created = []
    for item in payload:
        test_case = TestCase(**item.model_dump())
        created.append(await repo.create(test_case.model_dump()))
    return created


@router.get("", response_model=list[TestCase])
async def list_test_cases(
    skip: int = 0,
    limit: int = 100,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    return await repo.list(skip=skip, limit=limit)


@router.get("/{test_case_id}", response_model=TestCase)
async def get_test_case(
    test_case_id: str,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    doc = await repo.get(test_case_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case {test_case_id!r} not found.",
        )
    return doc


@router.put("/{test_case_id}", response_model=TestCase)
async def update_test_case(
    test_case_id: str,
    payload: TestCaseCreate,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> Any:
    if await repo.get(test_case_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case {test_case_id!r} not found.",
        )
    return await repo.update(test_case_id, payload.model_dump())


@router.delete("/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    test_case_id: str,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> None:
    if not await repo.delete(test_case_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case {test_case_id!r} not found.",
        )
