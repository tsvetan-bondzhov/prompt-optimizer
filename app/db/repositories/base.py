"""Shared repository helpers.

Standardizes the ID strategy (string UUIDs) and the conversion between Mongo
documents (which use ``_id``) and the domain-facing representation (which uses
``id``).

Domain Pydantic models are introduced in Task 04; until then the repositories
operate on plain ``dict`` documents. The conversion helpers below are written so
that when models arrive, a thin ``model.model_dump()`` / ``Model(**doc)`` adapter
can be layered on top without changing the storage format.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, MutableMapping, Optional

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase


def new_id() -> str:
    """Return a fresh standardized identifier (string UUID4)."""

    return str(uuid.uuid4())


def to_doc(data: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a domain-facing mapping into a Mongo document.

    Maps ``id`` -> ``_id`` and generates a new id when one is missing. The input
    mapping is not mutated.
    """

    doc = dict(data)
    _id = doc.pop("id", None)
    if _id is None:
        _id = doc.get("_id") or new_id()
    doc.pop("_id", None)
    doc["_id"] = _id
    return doc


def from_doc(doc: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Convert a Mongo document into a domain-facing dict (``_id`` -> ``id``)."""

    if doc is None:
        return None
    out: MutableMapping[str, Any] = dict(doc)
    if "_id" in out:
        out["id"] = out.pop("_id")
    return dict(out)


class BaseRepository:
    """Base class holding a database handle and resolving a collection.

    Repositories are dependency-injected with a :class:`AsyncIOMotorDatabase`
    handle so they can be exercised against a real Mongo or ``mongomock-motor``
    in tests.
    """

    #: Subclasses set the Mongo collection name.
    collection_name: str = ""

    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        if not self.collection_name:
            raise ValueError(
                f"{type(self).__name__} must define a 'collection_name'."
            )
        self._db = database
        self._collection: AsyncIOMotorCollection = database[self.collection_name]

    @property
    def collection(self) -> AsyncIOMotorCollection:
        """The underlying Motor collection (repository-internal use only)."""

        return self._collection
