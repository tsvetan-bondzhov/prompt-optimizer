"""Progress tracking & SSE infrastructure (Task 11).

Provides :class:`ProgressTracker`, a process-wide, ``run_id``-keyed publish /
subscribe hub for long-running evaluation and optimization jobs. It powers the
Server-Sent Events stream (Task 13) and persists progress to the run document so
a page reload can reconstruct current status.

Design:
  - Each ``run_id`` owns an in-memory :class:`ProgressState` (executed, total,
    current state, status, and a bounded ordered list of recent events) plus a
    set of per-subscriber :class:`asyncio.Queue`s.
  - :meth:`ProgressTracker.publish` normalizes an incoming event (including the
    raw dicts emitted by :class:`app.services.evaluator.EvaluatorService`), folds
    it into the run state, persists the updated progress, and fans it out to
    every live subscriber queue.
  - Persistence is decoupled: an optional async ``persist`` callback *or* a runs
    repository exposing ``update_progress`` is injected in the constructor. When
    neither is supplied persistence is skipped gracefully (no-op), keeping the
    tracker easy to unit-test.
  - :meth:`ProgressTracker.make_hook` returns a callable matching
    :data:`app.services.evaluator.ProgressHook`, so the tracker can be passed
    directly as the ``progress`` hook to ``EvaluatorService.run``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import utcnow

__all__ = [
    "ProgressEventType",
    "ProgressEvent",
    "ProgressState",
    "ProgressTracker",
    "PersistCallback",
]

logger = logging.getLogger(__name__)

#: Default bound on the number of events retained in memory per run. Older
#: events remain available from the persisted run document.
DEFAULT_MAX_EVENTS = 200

#: An async callable persisting a run's progress payload: ``(run_id, progress)``.
PersistCallback = Callable[[str, dict[str, Any]], Awaitable[Any]]


@runtime_checkable
class RunsRepositoryLike(Protocol):
    """Minimal protocol for a runs repository able to persist progress."""

    async def update_progress(
        self, run_id: str, progress: Mapping[str, Any]
    ) -> Any:  # pragma: no cover - structural typing only
        ...


class ProgressEventType(str, Enum):
    """The canonical set of progress event types streamed to clients."""

    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    ITERATION_DONE = "iteration_done"
    RUN_COMPLETED = "run_completed"
    RUN_CANCELLED = "run_cancelled"
    ERROR = "error"


class ProgressEvent(BaseModel):
    """A single normalized progress event.

    The evaluator emits looser dicts (keyed ``event``/``executed``/``total``/
    ``error`` etc.); :meth:`ProgressTracker.normalize` maps those into this
    schema before publication.
    """

    model_config = ConfigDict(extra="allow")

    type: ProgressEventType = Field(..., description="Canonical event type.")
    timestamp: datetime = Field(default_factory=utcnow)
    executed: Optional[int] = Field(default=None, ge=0)
    total: Optional[int] = Field(default=None, ge=0)
    current_state: Optional[str] = Field(
        default=None, description="Human-readable description of current activity."
    )
    message: Optional[str] = Field(default=None)
    report_id: Optional[str] = Field(default=None)


class ProgressState(BaseModel):
    """Current progress snapshot for one run, plus its recent events.

    Persisted to the run document so reconnecting clients (page reload) rebuild
    state from the snapshot before streaming live updates.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    executed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    current_state: Optional[str] = Field(
        default=None, description="Latest current_state / step description."
    )
    status: str = Field(
        default="pending",
        description="pending | running | completed | failed.",
    )
    events: list[ProgressEvent] = Field(
        default_factory=list, description="Bounded, ordered recent events."
    )
    updated_at: datetime = Field(default_factory=utcnow)


# Map the evaluator's raw ``event`` values onto canonical event types.
_RAW_EVENT_TYPE_MAP: dict[str, ProgressEventType] = {
    "executed": ProgressEventType.STEP_COMPLETED,
    "step_started": ProgressEventType.STEP_STARTED,
    "step_completed": ProgressEventType.STEP_COMPLETED,
    "iteration": ProgressEventType.ITERATION_DONE,
    "iteration_done": ProgressEventType.ITERATION_DONE,
    "completed": ProgressEventType.RUN_COMPLETED,
    "run_completed": ProgressEventType.RUN_COMPLETED,
    "cancelled": ProgressEventType.RUN_CANCELLED,
    "run_cancelled": ProgressEventType.RUN_CANCELLED,
    "error": ProgressEventType.ERROR,
}

# Event types that move a run into a terminal/active status.
_STATUS_BY_TYPE: dict[ProgressEventType, str] = {
    ProgressEventType.STEP_STARTED: "running",
    ProgressEventType.STEP_COMPLETED: "running",
    ProgressEventType.ITERATION_DONE: "running",
    ProgressEventType.RUN_COMPLETED: "completed",
    ProgressEventType.RUN_CANCELLED: "cancelled",
    ProgressEventType.ERROR: "failed",
}


class _RunChannel:
    """Per-run in-memory state: current snapshot + live subscriber queues."""

    def __init__(self, run_id: str, *, max_events: int) -> None:
        self.state = ProgressState(run_id=run_id)
        self.subscribers: set[asyncio.Queue[ProgressEvent]] = set()
        self._max_events = max_events

    def apply(self, event: ProgressEvent) -> None:
        """Fold an event into the run state and append to the bounded buffer."""

        if event.executed is not None:
            self.state.executed = event.executed
        if event.total is not None:
            self.state.total = event.total
        if event.current_state is not None:
            self.state.current_state = event.current_state
        self.state.status = _STATUS_BY_TYPE.get(event.type, self.state.status)
        self.state.updated_at = utcnow()

        self.state.events.append(event)
        if len(self.state.events) > self._max_events:
            # Drop oldest; persisted run document retains full history.
            del self.state.events[: len(self.state.events) - self._max_events]


class ProgressTracker:
    """Process-wide, ``run_id``-keyed progress pub/sub hub with persistence.

    A single instance is shared across services and routes (instantiated in the
    application lifespan — Task 12).
    """

    def __init__(
        self,
        *,
        persist: Optional[PersistCallback] = None,
        runs_repository: Optional[RunsRepositoryLike] = None,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> None:
        """:param persist: Optional async callback ``(run_id, progress)`` used to
            persist progress on every publish. Takes precedence over
            ``runs_repository`` when both are given.
        :param runs_repository: Optional repository exposing
            ``update_progress(run_id, progress)`` (e.g.
            :class:`app.db.repositories.runs.OptimizationRunRepository`). Used for
            persistence when ``persist`` is not supplied.
        :param max_events: Bound on retained in-memory events per run.
        """

        self._persist = persist
        self._runs_repository = runs_repository
        self._max_events = max_events
        self._channels: dict[str, _RunChannel] = {}
        self._lock = asyncio.Lock()

    # -- channel management ------------------------------------------------

    def _channel(self, run_id: str) -> _RunChannel:
        """Return (creating if needed) the channel for ``run_id``."""

        channel = self._channels.get(run_id)
        if channel is None:
            channel = _RunChannel(run_id, max_events=self._max_events)
            self._channels[run_id] = channel
        return channel

    # -- pub/sub -----------------------------------------------------------

    def subscribe(self, run_id: str) -> asyncio.Queue[ProgressEvent]:
        """Register and return a fresh subscriber queue for ``run_id``.

        Every published event is delivered to all registered queues. Callers
        should :meth:`unsubscribe` (or use :meth:`stream`) when done.
        """

        channel = self._channel(run_id)
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        channel.subscribers.add(queue)
        return queue

    def unsubscribe(
        self, run_id: str, subscriber: asyncio.Queue[ProgressEvent]
    ) -> None:
        """Remove a previously-registered subscriber queue for ``run_id``."""

        channel = self._channels.get(run_id)
        if channel is not None:
            channel.subscribers.discard(subscriber)

    async def publish(self, run_id: str, event: Any) -> ProgressEvent:
        """Normalize, apply, persist, and fan out a progress event.

        :param run_id: The run this event belongs to.
        :param event: A :class:`ProgressEvent`, a mapping (including the raw
            evaluator event dicts), or anything :meth:`normalize` accepts.
        :returns: The normalized :class:`ProgressEvent` that was published.
        """

        normalized = self.normalize(event)

        async with self._lock:
            channel = self._channel(run_id)
            channel.apply(normalized)
            subscribers = list(channel.subscribers)
            state_payload = channel.state.model_dump(mode="json")

        for queue in subscribers:
            queue.put_nowait(normalized)

        await self._persist_state(run_id, state_payload)
        return normalized

    async def stream(self, run_id: str) -> AsyncIterator[ProgressEvent]:
        """Async iterator yielding live events for ``run_id``.

        Note: this yields *live* events only. SSE endpoints should first send
        :meth:`snapshot` (state + recent events) on connect, then stream from
        here until a ``run_completed`` event arrives.
        """

        queue = self.subscribe(run_id)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.type in (
                    ProgressEventType.RUN_COMPLETED,
                    ProgressEventType.RUN_CANCELLED,
                ):
                    break
        finally:
            self.unsubscribe(run_id, queue)

    # -- snapshot / persistence -------------------------------------------

    def snapshot(self, run_id: str) -> Optional[ProgressState]:
        """Return a deep copy of the current in-memory state for ``run_id``.

        Returns ``None`` when nothing has been published for the run yet. The
        SSE endpoint sends this on connect so reconnecting clients rebuild state
        before consuming live updates.
        """

        channel = self._channels.get(run_id)
        if channel is None:
            return None
        return channel.state.model_copy(deep=True)

    async def _persist_state(
        self, run_id: str, state_payload: dict[str, Any]
    ) -> None:
        """Persist progress via the injected callback/repo; never raises."""

        try:
            if self._persist is not None:
                await self._persist(run_id, state_payload)
            elif self._runs_repository is not None:
                await self._runs_repository.update_progress(run_id, state_payload)
        except Exception:  # persistence must never break the run
            logger.exception("Failed to persist progress for run %s", run_id)

    # -- service integration ----------------------------------------------

    def make_hook(self, run_id: str) -> Callable[[dict[str, Any]], Awaitable[None]]:
        """Return an async progress hook bound to ``run_id``.

        The returned callable matches
        :data:`app.services.evaluator.ProgressHook` and can be passed directly as
        the ``progress`` argument to ``EvaluatorService.run``::

            tracker = ProgressTracker(runs_repository=runs)
            await evaluator.run(prompt, cases, n, run_id=rid,
                                progress=tracker.make_hook(rid))
        """

        async def _hook(event: dict[str, Any]) -> None:
            await self.publish(run_id, event)

        return _hook

    # -- normalization -----------------------------------------------------

    @staticmethod
    def normalize(event: Any) -> ProgressEvent:
        """Coerce any supported event representation into a :class:`ProgressEvent`.

        Accepts an existing :class:`ProgressEvent` (returned as-is), or a mapping
        such as the evaluator's raw dicts which use keys ``event`` (one of
        ``executed``/``completed``/``error``), ``executed``, ``total``, ``error``,
        ``run_id``, ``score``, etc. Unknown keys are preserved (``extra=allow``).
        """

        if isinstance(event, ProgressEvent):
            return event
        if not isinstance(event, Mapping):
            raise TypeError(
                f"Cannot normalize progress event of type {type(event)!r}; "
                "expected ProgressEvent or mapping."
            )

        data: dict[str, Any] = dict(event)

        # Resolve the canonical type. Prefer an explicit ``type`` field, else
        # map the evaluator's ``event`` discriminator.
        raw_type = data.pop("type", None)
        raw_event = data.pop("event", None)
        event_type = ProgressTracker._resolve_type(raw_type, raw_event, data)

        # An evaluator error event carries the message under ``error``.
        error_msg = data.pop("error", None)
        message = data.pop("message", None)
        if message is None and error_msg:
            message = str(error_msg)

        current_state = data.pop("current_state", None)
        if current_state is None:
            current_state = data.pop("current_step", None)

        return ProgressEvent(
            type=event_type,
            executed=data.pop("executed", None),
            total=data.pop("total", None),
            current_state=current_state,
            message=message,
            report_id=data.pop("report_id", None),
            **data,  # retain any extra context (run_id, score, test_case_id, ...)
        )

    @staticmethod
    def _resolve_type(
        raw_type: Any, raw_event: Any, data: Mapping[str, Any]
    ) -> ProgressEventType:
        """Best-effort resolution of the canonical event type."""

        for candidate in (raw_type, raw_event):
            if candidate is None:
                continue
            if isinstance(candidate, ProgressEventType):
                return candidate
            key = str(candidate).lower()
            if key in _RAW_EVENT_TYPE_MAP:
                return _RAW_EVENT_TYPE_MAP[key]
            try:
                return ProgressEventType(key)
            except ValueError:
                continue

        # No discriminator present: infer from payload (an ``error`` key implies
        # an error event, otherwise treat as a generic step completion).
        if data.get("error"):
            return ProgressEventType.ERROR
        return ProgressEventType.STEP_COMPLETED
