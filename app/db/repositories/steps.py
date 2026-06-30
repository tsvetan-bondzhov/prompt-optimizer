"""Repository for the ``optimization_steps`` collection.

One document per optimization iteration (proposed prompt + result links).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import COLLECTION_OPTIMIZATION_STEPS
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class OptimizationStepRepository(BaseRepository):
    """Insert/list ``OptimizationStep`` documents."""

    collection_name = COLLECTION_OPTIMIZATION_STEPS

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new optimization step."""

        doc = to_doc(data)
        doc.setdefault("created_at", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, step_id: str) -> Optional[dict[str, Any]]:
        """Fetch a step by id."""

        doc = await self.collection.find_one({"_id": step_id})
        return from_doc(doc)

    async def list_by_run(
        self, run_id: str, *, skip: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """List steps for a run, ordered by ``iteration_index`` ascending."""

        cursor = (
            self.collection.find({"run_id": run_id})
            .sort("iteration_index", 1)
            .skip(skip)
            .limit(limit)
        )
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def count_by_run(self, run_id: str) -> int:
        """Number of steps recorded for a run."""

        return await self.collection.count_documents({"run_id": run_id})
