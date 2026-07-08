"""Repository for the ``prompts`` collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import COLLECTION_PROMPTS
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class PromptRepository(BaseRepository):
    """Get/create/update ``Prompt`` documents.

    A prompt captures the current best prompt text for a goal/project.
    """

    collection_name = COLLECTION_PROMPTS

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new prompt."""

        doc = to_doc(data)
        doc.setdefault("updated_at", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, prompt_id: str) -> Optional[dict[str, Any]]:
        """Fetch a prompt by id."""

        doc = await self.collection.find_one({"_id": prompt_id})
        return from_doc(doc)

    async def get_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Fetch the prompt with a given ``name`` (indexed lookup)."""

        doc = await self.collection.find_one({"name": name})
        return from_doc(doc)

    async def list(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List prompts, paginated."""

        cursor = self.collection.find().skip(skip).limit(limit)
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def update(
        self, prompt_id: str, changes: Mapping[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Apply ``$set`` changes (always bumping ``updated_at``)."""

        updates = dict(changes)
        updates.pop("id", None)
        updates.pop("_id", None)
        updates["updated_at"] = datetime.now(timezone.utc)
        await self.collection.update_one({"_id": prompt_id}, {"$set": updates})
        return await self.get(prompt_id)

    async def delete(self, prompt_id: str) -> bool:
        """Delete a prompt; returns ``True`` if removed."""

        result = await self.collection.delete_one({"_id": prompt_id})
        return result.deleted_count > 0
