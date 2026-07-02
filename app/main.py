"""FastAPI application factory & lifespan wiring (Task 12).

``create_app()`` builds the application; the module-level ``app`` is the
uvicorn entry point (``uvicorn app.main:app``).

The lifespan handler owns process-wide resources:
  - connects the Motor client and creates the plan §5.1 indexes,
  - runs the registry bootstrap (``register_builtins``),
  - instantiates the singleton :class:`ProgressTracker`, persisting progress to
    the owning run document (optimization or standalone evaluation run),
  - exposes the shared handles on ``app.state`` (consumed by
    :mod:`app.api.deps`).

Tests inject a ``mongomock-motor`` database via ``create_app(database=...)``;
in that case the real Mongo connection lifecycle is skipped entirely.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.bootstrap import register_builtins
from app.db import client as db_client
from app.db.repositories import (
    EvaluationRunRepository,
    OptimizationRunRepository,
)
from app.logging_config import configure_logging
from app.services.progress import ProgressTracker

__all__ = ["create_app", "app"]

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "web" / "static"


def _make_progress_persister(db: AsyncIOMotorDatabase):
    """Persist a progress payload onto whichever run document owns ``run_id``.

    Optimization runs and standalone evaluation runs live in different
    collections; try the optimization run first (its repo returns ``None`` when
    the id is unknown), then fall back to the evaluation run.
    """

    optimization_runs = OptimizationRunRepository(db)
    evaluation_runs = EvaluationRunRepository(db)

    async def _persist(run_id: str, progress: dict[str, Any]) -> None:
        updated = await optimization_runs.update_progress(run_id, progress)
        if updated is None:
            await evaluation_runs.update(run_id, {"progress": dict(progress)})

    return _persist


def create_app(database: Optional[AsyncIOMotorDatabase] = None) -> FastAPI:
    """Build the FastAPI application.

    :param database: Optional pre-built database handle (tests pass a
        ``mongomock-motor`` database). When ``None`` the real Motor client is
        connected during the lifespan startup and closed on shutdown.
    """

    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        register_builtins()

        owns_client = database is None
        db = database if database is not None else db_client.get_database()

        try:
            await db_client.ensure_indexes(db)
        except Exception:  # noqa: BLE001 - index creation must not block startup
            logger.exception(
                "Could not create MongoDB indexes at startup; is Mongo "
                "reachable? Continuing — indexes are retried implicitly on "
                "next startup."
            )

        app.state.db = db
        app.state.progress_tracker = ProgressTracker(
            persist=_make_progress_persister(db)
        )
        logger.info("Application started (db=%s).", db.name)

        yield

        if owns_client:
            db_client.close()
        logger.info("Application shut down.")

    app = FastAPI(
        title="Prompt Optimizer",
        description=(
            "Modular, extensible prompt optimization framework — evaluator + "
            "optimizer feedback loop with a server-rendered UI."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _include_routers(app)
    return app


def _include_routers(app: FastAPI) -> None:
    """Attach the JSON API routers (Task 13) and web routes (Task 14).

    Routers are wired here as they land; the app factory stays the single
    composition point.
    """


app = create_app()
