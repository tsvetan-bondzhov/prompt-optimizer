"""Report detail routes (Task 13).

JSON API for fetching individual evaluation reports and optimization step
detail — consumed by API clients and the web templates (Task 14).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_report_repository, get_step_repository
from app.db.repositories import (
    EvaluationReportRepository,
    OptimizationStepRepository,
)

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports", response_model=list[dict])
async def list_reports(
    test_case_id: Optional[str] = None,
    run_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
    reports: EvaluationReportRepository = Depends(get_report_repository),
) -> Any:
    """List evaluation reports filtered by test case or run."""

    if run_id is not None:
        return await reports.list_by_run(run_id, skip=skip, limit=limit)
    if test_case_id is not None:
        return await reports.list_by_test_case(
            test_case_id, skip=skip, limit=limit
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Provide either 'run_id' or 'test_case_id' to filter reports.",
    )


@router.get("/reports/{report_id}", response_model=dict)
async def get_report(
    report_id: str,
    reports: EvaluationReportRepository = Depends(get_report_repository),
) -> Any:
    doc = await reports.get(report_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation report {report_id!r} not found.",
        )
    return doc


@router.get("/steps/{step_id}", response_model=dict)
async def get_step(
    step_id: str,
    steps: OptimizationStepRepository = Depends(get_step_repository),
) -> Any:
    doc = await steps.get(step_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization step {step_id!r} not found.",
        )
    return doc
