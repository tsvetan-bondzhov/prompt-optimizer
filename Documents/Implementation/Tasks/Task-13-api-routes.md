# Task 13 — API Routes

**Depends on:** 12
**Milestone:** Surface

## Objective
Expose all functionality through FastAPI routers: test case management, state
management, standalone evaluation, optimization, reports, and the SSE stream.

## Steps
1. `app/api/routes_testcases.py` — CRUD for test cases:
   - Create/list/get/update/delete. Body is JSON with `data` + `evaluation_criteria`
     (validate against `TestCaseCreate`). Support bulk JSON import.
2. State management (in `routes_optimization.py` or a dedicated `routes_state.py`):
   - Create/get/update `OptimizationState` (goal, current prompt, linked test cases).
   - List states.
3. `app/api/routes_evaluation.py`:
   - `POST /evaluations` — start a **standalone** evaluation for a given prompt +
     selected test cases + `executions_per_test_case`; returns `run_id`
     (scheduled via BackgroundTasks).
   - `GET /evaluations/{run_id}` — run status + summary.
   - `GET /evaluations/{run_id}/reports` — list evaluation reports (date, test
     case, prompt, prompt result, score, strengths, weaknesses, reasoning).
4. `app/api/routes_optimization.py`:
   - `POST /optimizations` — start an optimization loop for a `state_id` with a
     `RunConfig` (target_score, max_iterations, executions_per_test_case);
     returns `run_id`.
   - `GET /optimizations/{run_id}` — run status + progress.
   - `GET /optimizations/{run_id}/steps` — list `OptimizationStep`s (previous &
     proposed prompt, prev/new avg score, summarized reasoning, test cases, links
     to individual evaluation reports).
5. `app/api/routes_reports.py`:
   - Endpoints to fetch individual evaluation reports and optimization step detail
     (used by both API consumers and the web templates).
6. `app/api/routes_progress.py` — SSE:
   - `GET /progress/{run_id}/stream` returns an SSE stream (snapshot + live events)
     using the `ProgressTracker` (Task 11).
7. Decide response style: JSON for programmatic endpoints; the web routes (Task 14)
   may reuse these services and render HTML. Keep service logic out of routes.

## Files
- `app/api/routes_testcases.py`
- `app/api/routes_state.py`
- `app/api/routes_evaluation.py`
- `app/api/routes_optimization.py`
- `app/api/routes_reports.py`
- `app/api/routes_progress.py`

## Acceptance Criteria
- Full CRUD for test cases and states works against Mongo.
- Standalone evaluation and optimization can be started and return a `run_id`.
- Report/step listing endpoints return all fields required by the UI (plan §1 constraints).
- SSE endpoint streams live progress for an active run.
