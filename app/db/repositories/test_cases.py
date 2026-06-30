"""Repository for the ``test_cases`` collection (CRUD)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.db.client import COLLECTION_TEST_CASES
from app.db.repositories.base import BaseRepository, from_doc, to_doc


class TestCaseRepository(BaseRepository):
    """CRUD for test case documents.

    Works with plain dicts until the Task 04 ``TestCase`` model exists; callers
    pass/receive ``id`` (string UUID) rather than Mongo's ``_id``.
    """

    collection_name = COLLECTION_TEST_CASES

    async def create(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a new test case, returning the stored (domain-facing) doc."""

        doc = to_doc(data)
        doc.setdefault("created_at", datetime.now(timezone.utc))
        await self.collection.insert_one(doc)
        return from_doc(doc)  # type: ignore[return-value]

    async def get(self, test_case_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single test case by id, or ``None``."""

        doc = await self.collection.find_one({"_id": test_case_id})
        return from_doc(doc)

    async def list(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List test cases ordered by ``created_at`` ascending, paginated."""

        cursor = self.collection.find().sort("created_at", 1).skip(skip).limit(limit)
        return [from_doc(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]

    async def list_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fetch multiple test cases by their ids."""

        cursor = self.collection.find({"_id": {"$in": list(ids)}})
        return [from_doc(d) for d in await cursor.to_list(length=None)]  # type: ignore[misc]

    async def update(
        self, test_case_id: str, changes: Mapping[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Apply ``$set`` changes and return the updated document."""

        updates = dict(changes)
        updates.pop("id", None)
        updates.pop("_id", None)
        await self.collection.update_one({"_id": test_case_id}, {"$set": updates})
        return await self.get(test_case_id)

    async def delete(self, test_case_id: str) -> bool:
        """Delete a test case; returns ``True`` if a document was removed."""

        result = await self.collection.delete_one({"_id": test_case_id})
        return result.deleted_count > 0

    async def count(self) -> int:
        """Total number of test cases."""

        return await self.collection.count_documents({})
