"""Pydantic domain models and Mongo document schemas."""

from __future__ import annotations

from app.models.common import new_id, utcnow
from app.models.evaluation import (
    EvaluationPoint,
    EvaluationReport,
    EvaluationRun,
    EvaluationSummary,
    PromptEvaluation,
)
from app.models.optimization import (
    ImprovementContext,
    OptimizationRun,
    OptimizationState,
    OptimizationStep,
    RunConfig,
    RunProgress,
    RunStatus,
)
from app.models.prompt import Prompt, PromptResult
from app.models.test_case import TestCase, TestCaseCreate

__all__ = [
    # common
    "new_id",
    "utcnow",
    # prompt
    "Prompt",
    "PromptResult",
    # test case
    "TestCase",
    "TestCaseCreate",
    # evaluation
    "PromptEvaluation",
    "EvaluationPoint",
    "EvaluationReport",
    "EvaluationRun",
    "EvaluationSummary",
    # optimization
    "OptimizationState",
    "OptimizationRun",
    "OptimizationStep",
    "ImprovementContext",
    "RunConfig",
    "RunProgress",
    "RunStatus",
]
