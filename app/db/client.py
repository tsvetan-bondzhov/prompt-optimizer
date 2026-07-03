"""MongoDB connection management (async via Motor).

Provides a process-wide Motor client plus lifecycle hooks (:func:`connect` /
:func:`close`) intended to be wired into the FastAPI app lifespan, and
:func:`ensure_indexes` which creates the indexes declared in the implementation
plan (§5.1) idempotently.

No raw Mongo access should leak outside the repository layer; this module only
manages the client/database handles and index setup.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

# Collection name constants (single source of truth, plan §5.1).
COLLECTION_TEST_CASES = "test_cases"
COLLECTION_PROMPTS = "prompts"
COLLECTION_OPTIMIZATION_RUNS = "optimization_runs"
COLLECTION_OPTIMIZATION_STEPS = "optimization_steps"
COLLECTION_EVALUATION_RUNS = "evaluation_runs"
COLLECTION_EVALUATION_REPORTS = "evaluation_reports"


# Module-level singletons, populated by ``connect()``.
_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


def connect() -> AsyncIOMotorClient:
    """Create the global Motor client and database handle.

    Idempotent: repeated calls return the existing client. Safe to call from the
    application lifespan startup hook.
    """

    global _client, _database
    if _client is None:
        settings = get_settings()
        # Bounded server selection so startup index creation fails fast (and is
        # logged) instead of hanging when Mongo is unreachable.
        _client = AsyncIOMotorClient(
            settings.MONGO_URI, serverSelectionTimeoutMS=5000
        )
        _database = _client[settings.MONGO_DB]
    return _client


def close() -> None:
    """Close the global Motor client (lifespan shutdown hook)."""

    global _client, _database
    if _client is not None:
        _client.close()
        _client = None
        _database = None


def get_client() -> AsyncIOMotorClient:
    """Return the active Motor client, connecting lazily if needed."""

    if _client is None:
        connect()
    assert _client is not None  # for type-checkers
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """Return the active database handle, connecting lazily if needed."""

    if _database is None:
        connect()
    assert _database is not None  # for type-checkers
    return _database


async def ensure_indexes(database: Optional[AsyncIOMotorDatabase] = None) -> None:
    """Create all indexes from plan §5.1 idempotently.

    Indexes:
      - ``evaluation_reports.run_id``
      - ``optimization_steps.run_id``
      - ``test_cases.created_at``
      - ``prompts.name``

    ``create_index`` is idempotent in MongoDB (re-creating an identical index is
    a no-op), so this is safe to call on every startup. An optional ``database``
    handle may be supplied (useful for tests); otherwise the global one is used.
    """

    db = database if database is not None else get_database()

    await db[COLLECTION_EVALUATION_REPORTS].create_index("run_id")
    await db[COLLECTION_OPTIMIZATION_STEPS].create_index("run_id")
    await db[COLLECTION_TEST_CASES].create_index("created_at")
    await db[COLLECTION_PROMPTS].create_index("name")
