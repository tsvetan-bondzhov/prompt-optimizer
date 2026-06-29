# Task 12 — FastAPI App & Background Orchestration

**Depends on:** 08, 09, 11
**Milestone:** Surface

## Objective
Wire everything into a FastAPI application with dependency injection, lifespan
management, and BackgroundTasks-based job execution.

## Steps
1. `app/main.py` — app factory `create_app()`:
   - `lifespan` context: connect Mongo (Task 03), `ensure_indexes()`, run
     `bootstrap()` registrations (Task 05/07), instantiate the singleton
     `ProgressTracker`, and store shared singletons in `app.state`.
   - Mount static files and Jinja2 templates (Task 14).
   - Include routers (Task 13).
   - Initialize logging (Task 01).
2. Dependency providers (`app/api/deps.py`): functions returning repositories,
   services (`EvaluatorService`, `OptimizerService`, `SummarizerService`), and the
   `ProgressTracker` from `app.state` for injection into routes.
3. Background execution helper:
   - Endpoints that start an evaluation/optimization create the run document
     (status `pending`), schedule the work via `BackgroundTasks`, and return the
     `run_id` immediately (so the UI can redirect to the progress page).
   - The background coroutine sets status `running`, invokes the service with the
     `ProgressTracker`, and marks `completed`/`failed`. Ensure exceptions are
     caught and recorded (status `failed` + error event).
   - Confirm async services run correctly within BackgroundTasks (use a task
     wrapper that runs the coroutine on the event loop).
4. Root route → dashboard (Task 14).

## Files
- `app/main.py`
- `app/api/deps.py`
- `app/api/background.py` (run scheduling helper)

## Acceptance Criteria
- App starts via `uvicorn app.main:app`, connects to Mongo, registers impls.
- Starting a run returns a `run_id` immediately and executes in the background.
- Background failures mark the run `failed` and emit an error progress event.
