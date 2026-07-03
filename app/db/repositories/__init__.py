"""Repositories for MongoDB collections."""

from app.db.repositories.base import BaseRepository, from_doc, new_id, to_doc
from app.db.repositories.reports import (
    EvaluationReportRepository,
    EvaluationRunRepository,
)
from app.db.repositories.runs import OptimizationRunRepository
from app.db.repositories.prompts import PromptRepository
from app.db.repositories.steps import OptimizationStepRepository
from app.db.repositories.test_cases import TestCaseRepository

__all__ = [
    "BaseRepository",
    "new_id",
    "to_doc",
    "from_doc",
    "TestCaseRepository",
    "PromptRepository",
    "OptimizationRunRepository",
    "OptimizationStepRepository",
    "EvaluationRunRepository",
    "EvaluationReportRepository",
]
