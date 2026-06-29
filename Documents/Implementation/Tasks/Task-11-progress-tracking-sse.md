# Task 11 — Progress Tracking & SSE Infrastructure

**Depends on:** 03
**Milestone:** Surface

## Objective
Provide live progress for long-running evaluation/optimization jobs via a
`ProgressTracker` and a Server-Sent Events stream, with progress persisted so a
page reload reconstructs current status.

## Steps
1. `app/services/progress.py` — `ProgressTracker`:
   - Keyed by `run_id`; holds current `ProgressState` (executed, total,
     current_step, status, ordered list of step events).
   - Pub/sub via per-subscriber `asyncio.Queue`s; `subscribe(run_id)` /
     `publish(run_id, event)` / `unsubscribe`.
   - On each `publish`, also persist the updated progress to the run document
     (via runs repository) so reconnects rebuild state.
   - Define an `event` schema: `type` (`step_started|step_completed|iteration_done|run_completed|error`),
     `timestamp`, `executed`, `total`, `current_state`, `message`, optional `report_id`.
2. A singleton/process-wide tracker instance shared with services and routes
   (instantiated in app lifespan, Task 12).
3. SSE endpoint behaviour (implemented in Task 13 but specified here):
   - On connect, send a snapshot (current persisted progress + recent events),
     then stream live events from the subscription until `run_completed`.
4. Bounded event buffer per run to avoid unbounded memory; older events available
   from the persisted run document.

## Files
- `app/services/progress.py`

## Acceptance Criteria
- Multiple subscribers to the same `run_id` all receive events.
- Reconnecting after page reload yields the current snapshot then live updates.
- Progress is persisted to the run document and survives process-side reads.
