"""Repository for the ``optimization_states`` collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import COLLECTION_OPTIMIZATION_STATES
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class OptimizationStateRepository(BaseRepository):
    """Get/create/update ``OptimizationState`` documents.

    A state captures the current best prompt for a goal/project. Until the Task
    04 ``OptimizationState`` model exists, documents are plain dicts.
    """

    collection_name = COLLECTION_OPTIMIZATION_STATES

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new optimization state."""

        doc = to_doc(data)
        doc.setdefault("updated_at", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, state_id: str) -> Optional[dict[str, Any]]:
        """Fetch a state by id."""

        doc = await self.collection.find_one({"_id": state_id})
        return from_doc(doc)

    async def get_by_goal(self, goal: str) -> Optional[dict[str, Any]]:
        """Fetch the state for a given ``goal`` (indexed lookup)."""

        doc = await self.collection.find_one({"goal": goal})
        return from_doc(doc)

    async def list(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List optimization states, paginated."""

        cursor = self.collection.find().skip(skip).limit(limit)
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def update(
        self, state_id: str, changes: Mapping[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Apply ``$set`` changes (always bumping ``updated_at``)."""

        updates = dict(changes)
        updates.pop("id", None)
        updates.pop("_id", None)
        updates["updated_at"] = datetime.now(timezone.utc)
        await self.collection.update_one({"_id": state_id}, {"$set": updates})
        return await self.get(state_id)

    async def delete(self, state_id: str) -> bool:
        """Delete a state; returns ``True`` if removed."""

        result = await self.collection.delete_one({"_id": state_id})
        return result.deleted_count > 0
