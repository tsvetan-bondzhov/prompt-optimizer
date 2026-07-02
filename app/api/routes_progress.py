"""Server-Sent Events progress stream (Task 13, plan §6.4).

``GET /api/progress/{run_id}/stream`` first emits a ``snapshot`` event (the
current in-memory :class:`ProgressState`, falling back to the progress payload
persisted on the run document so page reloads reconstruct state), then streams
live events until the run reaches a terminal state or the client disconnects.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    get_evaluation_run_repository,
    get_optimization_run_repository,
    get_progress_tracker,
)
from app.db.repositories import (
    EvaluationRunRepository,
    OptimizationRunRepository,
)
from app.services.progress import ProgressEventType, ProgressTracker

router = APIRouter(prefix="/api/progress", tags=["progress"])

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@router.get("/{run_id}/stream")
async def stream_progress(
    run_id: str,
    request: Request,
    tracker: ProgressTracker = Depends(get_progress_tracker),
    optimization_runs: OptimizationRunRepository = Depends(
        get_optimization_run_repository
    ),
    evaluation_runs: EvaluationRunRepository = Depends(
        get_evaluation_run_repository
    ),
) -> EventSourceResponse:
    run_doc = await optimization_runs.get(run_id)
    if run_doc is None:
        run_doc = await evaluation_runs.get(run_id)

    in_memory = tracker.snapshot(run_id)
    if run_doc is None and in_memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No run found for id {run_id!r}.",
        )

    # Subscribe *before* taking the snapshot so no event published in between
    # is lost; the queue buffers anything that arrives while we send it.
    queue = tracker.subscribe(run_id)

    snapshot: dict[str, Any] = _build_snapshot(run_id, in_memory, run_doc)
    run_status: Optional[str] = snapshot.get("status")
    if run_doc is not None and run_doc.get("status") in _TERMINAL_STATUSES:
        run_status = run_doc["status"]

    async def event_stream():
        try:
            yield {"event": "snapshot", "data": json.dumps(snapshot)}
            if run_status in _TERMINAL_STATUSES:
                return
            while True:
                if await request.is_disconnected():
                    return
                event = await queue.get()
                yield {
                    "event": event.type.value,
                    "data": event.model_dump_json(),
                }
                if event.type in (
                    ProgressEventType.RUN_COMPLETED,
                    ProgressEventType.ERROR,
                ):
                    return
        finally:
            tracker.unsubscribe(run_id, queue)

    return EventSourceResponse(event_stream())


def _build_snapshot(
    run_id: str, in_memory: Any, run_doc: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Prefer the live in-memory state; fall back to the persisted progress."""

    if in_memory is not None:
        return in_memory.model_dump(mode="json")
    persisted = (run_doc or {}).get("progress") or {}
    if persisted:
        persisted.setdefault("run_id", run_id)
        # Persisted RunProgress uses ``current_step``; ProgressState uses
        # ``current_state`` — expose both so clients handle either shape.
        persisted.setdefault(
            "current_state", persisted.get("current_step")
        )
        if run_doc and run_doc.get("status"):
            persisted["status"] = run_doc["status"]
        return persisted
    return {
        "run_id": run_id,
        "executed": 0,
        "total": 0,
        "current_state": None,
        "status": (run_doc or {}).get("status", "pending"),
        "events": [],
    }
