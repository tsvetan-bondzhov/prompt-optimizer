"""Optimization models.

Covers the persisted best state (:class:`OptimizationState`), a single loop
invocation (:class:`OptimizationRun`) with its config and progress, one
iteration (:class:`OptimizationStep`), and the improver input
(:class:`ImprovementContext`).

Field names match :mod:`app.db.repositories.states`,
:mod:`app.db.repositories.runs`, and :mod:`app.db.repositories.steps`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.models.common import new_id, utcnow
from app.models.evaluation import EvaluationSummary


class RunStatus(str, Enum):
    """Lifecycle status of an optimization run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunConfig(BaseModel):
    """Tunable parameters for an optimization run (defaults from settings)."""

    model_config = ConfigDict(extra="forbid")

    target_score: float = Field(
        default_factory=lambda: get_settings().DEFAULT_TARGET_SCORE,
        ge=1,
        le=10,
    )
    max_iterations: int = Field(
        default_factory=lambda: get_settings().DEFAULT_MAX_ITERATIONS,
        ge=1,
    )
    executions_per_test_case: int = Field(
        default_factory=lambda: get_settings().DEFAULT_EXECUTIONS_PER_TEST_CASE,
        ge=1,
    )


class OptimizationState(BaseModel):
    """The current best state for a goal/project."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    goal: str = Field(..., min_length=1)
    current_prompt: str = Field(..., description="Current best prompt text.")
    avg_score: float | None = Field(default=None, ge=1, le=10)
    test_case_ids: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")
    updated_at: datetime = Field(default_factory=utcnow)


class RunProgress(BaseModel):
    """Persisted progress for a run (reconstructs status on page reload)."""

    model_config = ConfigDict(extra="forbid")

    executed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    current_step: str | None = Field(default=None)
    status: RunStatus = Field(default=RunStatus.PENDING)
    events: list[dict[str, Any]] = Field(default_factory=list)


class OptimizationRun(BaseModel):
    """A single optimization loop invocation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    state_id: str
    config: RunConfig = Field(default_factory=RunConfig)
    status: RunStatus = Field(default=RunStatus.PENDING)
    progress: RunProgress = Field(default_factory=RunProgress)
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None)


class OptimizationStep(BaseModel):
    """One optimization iteration (proposed prompt + result links)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    run_id: str
    iteration_index: int = Field(..., ge=0)
    previous_prompt: str
    proposed_prompt: str
    previous_avg_score: float | None = Field(default=None, ge=1, le=10)
    new_avg_score: float | None = Field(default=None, ge=1, le=10)
    summarized_reasoning: str = Field(default="")
    summary: EvaluationSummary = Field(default_factory=EvaluationSummary)
    test_case_ids: list[str] = Field(default_factory=list)
    evaluation_report_ids: list[str] = Field(default_factory=list)
    accepted: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)


class ImprovementContext(BaseModel):
    """Input handed to a :class:`PromptImprover` to propose a better prompt."""

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(..., min_length=1)
    current_prompt: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    avg_score: float | None = Field(default=None, ge=1, le=10)
    reasoning: str = Field(default="")
    system_prompt: str | None = Field(default=None)
