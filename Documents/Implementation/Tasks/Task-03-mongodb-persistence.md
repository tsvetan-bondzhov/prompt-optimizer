# Task 03 — MongoDB Persistence Layer

**Depends on:** 01
**Milestone:** Foundation

## Objective
Async MongoDB access via Motor, with a repository per collection and index setup.

## Steps
1. `app/db/client.py`:
   - Create a Motor client from `settings.MONGO_URI` and a `get_database()` helper.
   - Provide `connect()` / `close()` lifecycle hooks (called from app lifespan).
   - `ensure_indexes()` creating indexes from plan §5.1.
2. Create the repository pattern under `app/db/repositories/` — one module each:
   - `test_cases.py` — CRUD for test cases.
   - `states.py` — get/create/update `OptimizationState`.
   - `runs.py` — create/update `OptimizationRun` (status + progress).
   - `steps.py` — insert/list `OptimizationStep`.
   - `reports.py` — insert/list `EvaluationReport`, plus `EvaluationRun` grouping.
3. Each repository:
   - Accepts a `Database` handle (dependency-injected, testable).
   - Converts between Pydantic models (Task 04) and Mongo documents (`_id` ↔ `id`).
   - Exposes async methods with type hints; pagination/filtering where relevant
     (e.g. list reports by `run_id`, list steps by `run_id`).
4. Use string UUIDs or Mongo `ObjectId` consistently; standardize an ID helper.

## Files
- `app/db/client.py`
- `app/db/repositories/{test_cases,states,runs,steps,reports}.py`

## Acceptance Criteria
- Repositories perform round-trip create/read against a test Mongo
  (`mongomock-motor` or container).
- `ensure_indexes()` creates all indexes from plan §5.1 idempotently.
- No raw Mongo access leaks outside the repository layer.
