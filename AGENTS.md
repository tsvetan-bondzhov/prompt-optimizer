# AGENTS.md — Prompt Optimizer

Canonical commands and conventions for contributors and coding agents.

## Commands

| Action | Command |
|--------|---------|
| Run (dev) | `uvicorn app.main:app --reload` (needs Mongo; set `MONGO_URI=mongodb://localhost:27017` in `.env`) |
| Run (Docker) | `docker compose -f docker/docker-compose.yml up --build` |
| Tests | `pytest` (fully offline: mongomock + fakes, no LLM calls) |
| Install deps | `pip install -e .[dev]` (Python 3.11+, venv in `.venv/`) |
| Offline mode | set `ACTIVE_LLM_RUNNER=fake` (no Claude CLI needed) |

There is no configured linter/formatter; follow the existing style (PEP 8,
double quotes, ~88 col, Google-style docstrings with `:param:`).

## Architecture (short)

- `app/config.py` — pydantic-settings; all knobs are `ACTIVE_*` / `DEFAULT_*`
  env vars (see `.env.example`). `get_settings()` is `lru_cache`d.
- `app/core/` — ABCs (`interfaces.py`) + name-based implementation registry
  (`registry.py`); `bootstrap.register_builtins()` (idempotent) registers all
  built-ins and must run before resolving anything.
- `app/implementations/` — user-swappable reference impls (executor,
  evaluation steps, improver, summarizer). They self-register at import.
- `app/services/` — `EvaluatorService` (reports = test_cases × N),
  `OptimizerService` (feedback loop; acceptance is **strictly greater** score),
  `SummarizerService`, `ProgressTracker` (run_id-keyed pub/sub + persisted
  progress).
- `app/db/` — Motor client (`client.py`, collection-name constants, indexes)
  + repositories. Docs use string UUID4 ids (`_id` ↔ `id` mapping in
  `repositories/base.py`). No raw Mongo access outside repositories.
- `app/api/` — JSON API under `/api`; runs are created `pending`, executed via
  FastAPI `BackgroundTasks` (`background.py`), `run_id` returned immediately.
  SSE at `/api/progress/{run_id}/stream`.
- `app/web/` — Jinja2 templates + `routes.py` (server-rendered UI reusing the
  same repos/services; no business logic in routes).

## Conventions / gotchas

- **Dependency injection everywhere**: services take repositories +
  resolver callables; tests override resolvers instead of patching.
- Route handlers get shared singletons from `app.state` (`db`,
  `progress_tracker`) via `app/api/deps.py`; tests inject mongomock through
  `create_app(database=...)`.
- Register routes with literal path segments (e.g. `/test-cases/import`)
  **before** parameterized ones (`/test-cases/{id}`) — FastAPI matches in
  declaration order.
- `PromptEvaluation` is strict: 1–3 strengths/weaknesses, non-empty reasoning,
  integer score 1–10. Aggregated scores are floats clamped to [1, 10].
- Editing a state's prompt (API or UI) intentionally resets `avg_score` and the
  summary; the next optimization run re-establishes a baseline.
- Progress events: evaluator emits raw dicts (`event: executed/completed/...`);
  `ProgressTracker.normalize` maps them to canonical types. Progress hooks and
  persistence must never raise into the run.
- Sprint tracking lives in `Documents/Implementation/SPRINT.md`; the plan and
  per-task specs in `Documents/Implementation/`.
