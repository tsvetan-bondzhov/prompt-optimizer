# Task 14 — Web UI (Jinja2 + SSE)

**Depends on:** 13
**Milestone:** Surface

## Objective
Build the server-rendered Jinja2 UI for managing state and test cases, running
evaluations and optimizations, viewing live progress, and browsing reports.

## Steps
1. Layout & assets:
   - `app/web/templates/base.html` — shared layout, nav (Dashboard, Test Cases,
     States, Runs, Reports).
   - `app/web/static/` — minimal CSS and a small JS helper for SSE
     (`EventSource`) progress rendering. HTMX optional for partial updates.
2. Pages:
   - **Dashboard** — list of states, recent runs (eval + optimization) with status.
   - **Test Cases** — list + create/edit form (JSON editor for `data` and
     `evaluation_criteria`), delete, bulk import.
   - **State** — create/edit an `OptimizationState` (goal, current prompt, choose
     test cases); show current avg score + summary.
   - **Run Evaluation** — form to pick a prompt (or state's prompt) + test cases +
     `executions_per_test_case`; submit starts a standalone evaluation and
     redirects to the progress page.
   - **Run Optimization** — form to pick a state + `RunConfig` (target_score,
     max_iterations, executions_per_test_case); submit starts the loop and
     redirects to the progress page.
   - **Progress page** (`/runs/{run_id}`) — subscribes to the SSE stream and shows
     executed/remaining steps, current state, and a growing report of each step
     executed so far. On load, renders the persisted snapshot then live updates.
   - **Validation reports view** — table of evaluation reports (date, test case,
     prompt, prompt result, score, strengths, weaknesses, reasoning) with detail.
   - **Optimization reports view** — list of optimization steps (previous prompt,
     proposed prompt, previous avg score, new avg score, summarized reasoning,
     test cases, accepted flag) with links to individual evaluation reports.
3. Web routes (in `app/web/routes.py` or extend API routers) render these
   templates by calling the same services/repositories used by the JSON API.
4. UX details: show prompt diffs (previous vs proposed) where helpful; color-code
   accepted/rejected steps; display scores prominently.

## Files
- `app/web/templates/{base,dashboard,test_cases,test_case_form,state,state_form,run_evaluation,run_optimization,progress,evaluation_reports,evaluation_report_detail,optimization_steps,optimization_step_detail}.html`
- `app/web/static/{styles.css,progress.js}`
- `app/web/routes.py`

## Acceptance Criteria
- Users can manage test cases and states entirely from the UI.
- Standalone evaluation and optimization can be launched from the UI.
- The progress page shows live, incrementally-updating step reports via SSE and
  survives a page reload (rebuilds from persisted progress).
- Validation and optimization reports display every field listed in plan §1.
