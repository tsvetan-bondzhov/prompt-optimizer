"""Test case models.

A ``TestCase`` is an input fixture for prompt execution. ``data`` holds the
inputs handed to the executor and ``evaluation_criteria`` holds whatever the
user-supplied evaluation steps need to score a result.

Stored documents use a string UUID ``id`` and a ``created_at`` timestamp,
matching :mod:`app.db.repositories.test_cases`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import new_id, utcnow


class TestCaseCreate(BaseModel):
    """Request payload for creating a test case (API/service input)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Human-readable name.")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Inputs handed to the executor."
    )
    evaluation_criteria: dict[str, Any] = Field(
        default_factory=dict,
        description="Criteria consumed by user evaluation steps.",
    )


class TestCase(BaseModel):
    """A stored test case document."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    name: str = Field(..., min_length=1, description="Human-readable name.")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Inputs handed to the executor."
    )
    evaluation_criteria: dict[str, Any] = Field(
        default_factory=dict,
        description="Criteria consumed by user evaluation steps.",
    )
    created_at: datetime = Field(default_factory=utcnow)
