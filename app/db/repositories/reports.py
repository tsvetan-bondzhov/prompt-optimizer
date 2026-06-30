"""Repositories for evaluation persistence.

Covers two collections:
  - ``evaluation_reports`` — one document per evaluation point (linked to a run).
  - ``evaluation_runs``    — one document per evaluator invocation (grouping).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import (
    COLLECTION_EVALUATION_REPORTS,
    COLLECTION_EVALUATION_RUNS,
)
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class EvaluationRunRepository(BaseRepository):
    """Create/update/list ``EvaluationRun`` grouping documents."""

    collection_name = COLLECTION_EVALUATION_RUNS

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new evaluation run."""

        doc = to_doc(data)
        doc.setdefault("created_at", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch an evaluation run by id."""

        doc = await self.collection.find_one({"_id": run_id})
        return from_doc(doc)

    async def update(
        self, run_id: str, changes: Mapping[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Apply ``$set`` changes (e.g. avg_score, status) to an evaluation run."""

        updates = dict(changes)
        updates.pop("id", None)
        updates.pop("_id", None)
        await self.collection.update_one({"_id": run_id}, {"$set": updates})
        return await self.get(run_id)

    async def list(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List evaluation runs (newest first), paginated."""

        cursor = self.collection.find().sort("created_at", -1).skip(skip).limit(limit)
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]


class EvaluationReportRepository(BaseRepository):
    """Insert/list ``EvaluationReport`` documents (one per evaluation point)."""

    collection_name = COLLECTION_EVALUATION_REPORTS

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a single evaluation report."""

        doc = to_doc(data)
        doc.setdefault("date", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def create_many(
        self, items: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Bulk-insert evaluation reports, returning the stored docs."""

        if not items:
            return []
        docs = []
        for item in items:
            doc = to_doc(item)
            doc.setdefault("date", datetime.now(timezone.utc))
            docs.append(doc)
        await self.collection.insert_many(docs)
        return [from_doc(d) for d in docs]  # type: ignore[misc]

    async def get(self, report_id: str) -> Optional[dict[str, Any]]:
        """Fetch a report by id."""

        doc = await self.collection.find_one({"_id": report_id})
        return from_doc(doc)

    async def list_by_run(
        self, run_id: str, *, skip: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """List reports for an evaluation run (indexed by ``run_id``)."""

        cursor = (
            self.collection.find({"run_id": run_id})
            .sort("date", 1)
            .skip(skip)
            .limit(limit)
        )
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def list_by_test_case(
        self, test_case_id: str, *, skip: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """List reports for a given test case (newest first)."""

        cursor = (
            self.collection.find({"test_case_id": test_case_id})
            .sort("date", -1)
            .skip(skip)
            .limit(limit)
        )
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def count_by_run(self, run_id: str) -> int:
        """Number of reports recorded for an evaluation run."""

        return await self.collection.count_documents({"run_id": run_id})
