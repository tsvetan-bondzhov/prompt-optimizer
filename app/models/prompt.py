"""PromptText-related value objects.

These are small, JSON-serializable Pydantic v2 models shared across the
evaluator, optimizer, and persistence layers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PromptText(BaseModel):
    """A prompt value object — the text fed to a :class:`PromptExecutor`."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="The prompt text.")


class PromptResult(BaseModel):
    """The output produced by executing a prompt against a test case."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="The raw output text of the execution.")
