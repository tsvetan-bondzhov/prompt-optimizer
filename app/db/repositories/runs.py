"""Repository for the ``optimization_runs`` collection.

A run is a single optimization loop invocation. This repository also covers the
common operations of updating run ``status`` and ``progress`` as the loop runs
(persisted progress lets a page reload reconstruct current status — plan §6.4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import COLLECTION_OPTIMIZATION_RUNS
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class OptimizationRunRepository(BaseRepository):
    """Create/update ``OptimizationRun`` documents (status + progress)."""

    collection_name = COLLECTION_OPTIMIZATION_RUNS

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new optimization run."""

        doc = to_doc(data)
        now = datetime.now(timezone.utc)
        doc.setdefault("created_at", now)
        doc.setdefault("status", "pending")
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch a run by id."""

        doc = await self.collection.find_one({"_id": run_id})
        return from_doc(doc)

    async def list_by_state(
        self, state_id: str, *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List runs for a given ``state_id`` (newest first)."""

        cursor = (
            self.collection.find({"state_id": state_id})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def list(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List all runs (newest first), paginated."""

        cursor = self.collection.find().sort("created_at", -1).skip(skip).limit(limit)
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def update(
        self, run_id: str, changes: Mapping[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Apply arbitrary ``$set`` changes to a run."""

        updates = dict(changes)
        updates.pop("id", None)
        updates.pop("_id", None)
        await self.collection.update_one({"_id": run_id}, {"$set": updates})
        return await self.get(run_id)

    async def update_status(
        self, run_id: str, status: str
    ) -> Optional[dict[str, Any]]:
        """Update only the run ``status`` (e.g. running/completed/failed)."""

        updates: dict[str, Any] = {"status": status}
        if status in ("completed", "failed", "cancelled"):
            updates["finished_at"] = datetime.now(timezone.utc)
        elif status == "running":
            updates["started_at"] = datetime.now(timezone.utc)
        await self.collection.update_one({"_id": run_id}, {"$set": updates})
        return await self.get(run_id)

    async def update_progress(
        self, run_id: str, progress: Mapping[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Persist the run ``progress`` payload (for reload/SSE reconstruction)."""

        await self.collection.update_one(
            {"_id": run_id}, {"$set": {"progress": dict(progress)}}
        )
        return await self.get(run_id)
