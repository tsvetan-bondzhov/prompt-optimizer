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

from app.config import get_settings
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
            "Per-data-entry criteria, aligned by index with 'data'. Resolved "
            "per key: keys missing from an entry fall back to "
            "'evaluation_criteria'."
        ),
    )
    evaluation_criteria: dict[str, Any] = Field(
        default_factory=dict,
        description="Dataset-level criteria (per-key fallback for all entries).",
    )
    grader_names: list[str] = Field(
        default_factory=list,
        description="Registered grader names to execute for this test case.",
    )
    executor_name: str = Field(
        default="default",
        min_length=1,
        description="Registered executor used to run the prompt.",
    )
    executor_llm_runner: str = Field(
        default_factory=lambda: get_settings().ACTIVE_LLM_RUNNER,
        min_length=1,
        description="LLM runner the executor delegates prompt execution to.",
    )
    executor_llm_runner_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Runner-specific options for the executor's LLM runner "
        "(e.g. model, effort, temperature; empty values are ignored).",
    )

    @field_validator("data", mode="before")
    @classmethod
    def _data_as_list(cls, value: Any) -> Any:
        return _coerce_data_entries(value)


class TestCaseCreate(_TestCaseFields):
    """Request payload for creating a test case (API/service input)."""


class TestCase(_TestCaseFields):
    """A stored test case document.

    Unknown keys are ignored (rather than rejected) so documents written by
    older versions — e.g. with the since-moved ``summarizer_llm_runner``
    fields — still validate.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)

    def criteria_for_entry(self, entry_index: int) -> dict[str, Any]:
        """Effective criteria for ``entry_index``, resolved **per key**.

        A key is taken from the entry's own criteria when present there and
        falls back to the dataset-level ``evaluation_criteria`` otherwise, so
        different keys can live at different levels (e.g. ``expected_json``
        per entry while ``json_schema`` is defined once for the dataset).
        """

        merged: dict[str, Any] = dict(self.evaluation_criteria or {})
        per_entry = self.evaluation_criteria_per_entry
        if 0 <= entry_index < len(per_entry) and per_entry[entry_index]:
            merged.update(per_entry[entry_index])
        return merged
