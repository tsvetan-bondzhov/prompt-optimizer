"""Test case models.

A ``TestCase`` is an input fixture for prompt execution. ``data`` is an
**array of data entries** (objects); each entry is executed individually by
the executor and its result graded on its own — the test case's score is the
average over all entries.

Evaluation criteria are split in two:

- ``evaluation_criteria_per_entry`` — a list aligned by index with ``data``;
  the criteria graders use for that specific entry.
- ``evaluation_criteria`` — dataset-level criteria used as the fallback when
  an entry has no per-entry criteria.

Stored documents use a string UUID ``id`` and a ``created_at`` timestamp,
matching :mod:`app.db.repositories.test_cases`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.common import new_id, utcnow


def _coerce_data_entries(value: Any) -> list[dict[str, Any]]:
    """Coerce legacy single-object ``data`` into a one-entry list."""

    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return value


class _TestCaseFields(BaseModel):
    """Fields shared by the create payload and the stored document."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Human-readable name.")
    data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Data entries; each is executed and graded individually.",
    )
    evaluation_criteria_per_entry: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Per-data-entry criteria, aligned by index with 'data'. Graders "
            "fall back to 'evaluation_criteria' when an entry has none."
        ),
    )
    evaluation_criteria: dict[str, Any] = Field(
        default_factory=dict,
        description="Dataset-level criteria (fallback for all entries).",
    )
    grader_names: list[str] = Field(
        default_factory=list,
        description="Registered grader names to execute for this test case.",
    )

    @field_validator("data", mode="before")
    @classmethod
    def _data_as_list(cls, value: Any) -> Any:
        return _coerce_data_entries(value)


class TestCaseCreate(_TestCaseFields):
    """Request payload for creating a test case (API/service input)."""


class TestCase(_TestCaseFields):
    """A stored test case document."""

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)

    def criteria_for_entry(self, entry_index: int) -> dict[str, Any]:
        """Criteria for ``entry_index``: per-entry first, dataset fallback."""

        per_entry = self.evaluation_criteria_per_entry
        if 0 <= entry_index < len(per_entry) and per_entry[entry_index]:
            return per_entry[entry_index]
        return self.evaluation_criteria or {}
