"""Repository for the ``prompt_versions`` collection.

One document per superseded prompt version — snapshotted by the optimizer
whenever an accepted iteration replaces a prompt's ``current_prompt``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import COLLECTION_PROMPT_VERSIONS
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class PromptVersionRepository(BaseRepository):
    """Insert/list ``PromptVersion`` documents."""

    collection_name = COLLECTION_PROMPT_VERSIONS

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new prompt version."""

        doc = to_doc(data)
        doc.setdefault("created_at", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, version_id: str) -> Optional[dict[str, Any]]:
        """Fetch a version by id."""

        doc = await self.collection.find_one({"_id": version_id})
        return from_doc(doc)

    async def list_by_prompt(
        self, prompt_id: str, *, skip: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """List a prompt's versions, newest (highest number) first."""

        cursor = (
            self.collection.find({"prompt_id": prompt_id})
            .sort("version_number", -1)
            .skip(skip)
            .limit(limit)
        )
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def list_by_run(
        self, run_id: str, *, skip: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """List the versions superseded during one optimization run."""

        cursor = (
            self.collection.find({"run_id": run_id})
            .sort("version_number", 1)
            .skip(skip)
            .limit(limit)
        )
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def next_version_number(self, prompt_id: str) -> int:
        """The next free version number for a prompt (1-based, monotonic)."""

        cursor = (
            self.collection.find({"prompt_id": prompt_id})
            .sort("version_number", -1)
            .limit(1)
        )
        latest = await cursor.to_list(length=1)
        if not latest:
            return 1
        return int(latest[0].get("version_number", 0)) + 1

    async def delete_by_prompt(self, prompt_id: str) -> int:
        """Delete all versions of a prompt; returns the number removed."""

        result = await self.collection.delete_many({"prompt_id": prompt_id})
        return result.deleted_count
