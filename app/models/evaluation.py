"""Evaluation models.

Covers the output of individual graders (:class:`PromptEvaluation`),
the in-memory aggregation of a single evaluation point
(:class:`EvaluationPoint`), the persisted point (:class:`EvaluationReport`), the
grouping run (:class:`EvaluationRun`), and the merged summary
(:class:`EvaluationSummary`).

Field names match :mod:`app.db.repositories.reports`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.common import new_id, utcnow


class PromptEvaluation(BaseModel):
    """Structured result of a single grader.

    Constraints (plan §5):
      - ``score`` is an integer in ``[1, 10]``.
      - ``strengths`` / ``weaknesses`` hold up to 3 non-empty items each
        (empty lists are fine — only report what adds information).
      - ``reasoning`` is a non-empty string.
    """

    model_config = ConfigDict(extra="forbid")

    strengths: list[str] = Field(default_factory=list, max_length=3)
    weaknesses: list[str] = Field(default_factory=list, max_length=3)
    reasoning: str = Field(..., min_length=1)
    score: int = Field(..., ge=1, le=10)
    grader_name: str | None = Field(
        default=None, description="Name of the grader that produced this."
    )

    @field_validator("strengths", "weaknesses")
    @classmethod
    def _no_blank_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("list items must be non-empty strings")
        return cleaned

    @field_validator("reasoning")
    @classmethod
    def _reasoning_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reasoning must be a non-empty string")
        return value


class DataEntryResult(BaseModel):
    """The executed + graded outcome of a single data entry."""

    model_config = ConfigDict(extra="forbid")

    entry_index: int = Field(..., ge=0)
    prompt_result: str = Field(..., description="The execution output text.")
    grader_evaluations: list[PromptEvaluation] = Field(default_factory=list)
    score: float = Field(..., ge=1, le=10)


class EvaluationPoint(BaseModel):
    """One ``(test_case × execution_index)`` evaluation, in memory.

    Each data entry of the test case is executed and graded individually
    (see :class:`DataEntryResult`); ``aggregated_score`` is the mean of the
    per-entry scores. ``prompt_result`` and ``grader_evaluations`` are the
    flattened views across all entries (kept for reports/summaries).
    """

    model_config = ConfigDict(extra="forbid")

    test_case_id: str
    execution_index: int = Field(..., ge=0)
    prompt_result: str = Field(..., description="The execution output text.")
    entry_results: list[DataEntryResult] = Field(default_factory=list)
    grader_evaluations: list[PromptEvaluation] = Field(default_factory=list)
    aggregated_score: float = Field(..., ge=1, le=10)


class EvaluationSummary(BaseModel):
    """Merged strengths/weaknesses/reasoning across many evaluation points."""

    model_config = ConfigDict(extra="forbid")

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")


class EvaluationReport(BaseModel):
    """A persisted evaluation point (one document per ``(test_case, i)``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    date: datetime = Field(default_factory=utcnow)
    run_id: str | None = Field(
        default=None, description="Owning evaluation run id."
    )
    test_case_id: str
    prompt: str = Field(..., description="The prompt text under evaluation.")
    prompt_name: str | None = Field(
        default=None, description="Name of the stored prompt, when one was used."
    )
    prompt_result: str = Field(..., description="The execution output text.")
    score: float = Field(..., ge=1, le=10)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")
    grader_evaluations: list[PromptEvaluation] = Field(default_factory=list)
    entry_results: list[DataEntryResult] = Field(default_factory=list)


class EvaluationRun(BaseModel):
    """A grouping document for one evaluator invocation.

    Standalone (UI) or loop-internal; reports link back via ``run_id``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)
    prompt: str = Field(..., description="The prompt text evaluated by this run.")
    prompt_name: str | None = Field(
        default=None, description="Name of the stored prompt, when one was used."
    )
    test_case_ids: list[str] = Field(default_factory=list)
    executions_per_test_case: int = Field(default=1, ge=1)
    avg_score: float | None = Field(
        default=None, description="Mean aggregated score across all points."
    )
    status: str = Field(default="completed")
    metadata: dict[str, Any] = Field(default_factory=dict)
