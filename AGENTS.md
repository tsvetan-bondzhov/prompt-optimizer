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

- `app/config.py` — pydantic-settings; knobs are `ACTIVE_*` / `DEFAULT_*`
  env vars (see `.env.example`). `get_settings()` is `lru_cache`d. The
  `ACTIVE_*` values are only **defaults** — executors, graders, and LLM
  runners are selected per test case / per prompt.
- `app/core/` — ABCs (`interfaces.py`: `PromptExecutor`, `Grader`,
  `PromptOptimizer`, `Summarizer`, `LLMRunner`) + name-based implementation
  registry (`registry.py`); `bootstrap.register_builtins()` (idempotent)
  registers all built-ins and must run before resolving anything.
- `app/implementations/` — user-swappable reference impls (executors under
  `executor`/`template`, graders under their own names incl. the LLM-judge
  `model_grader`, optimizer, summarizer). They self-register at import.
- `app/llm/` — `LLMRunner` transports: `claude_code`, `ollama`, `fake`.
  Executors never call providers directly; they receive the runner selected
  on the test case.
- `app/services/` — `EvaluatorService` (reports = test_cases × N; each
  test case's `data` entries are executed/graded individually and averaged),
  `OptimizerService` (feedback loop; acceptance is **strictly greater**
  score), `SummarizerService`, `ProgressTracker` (run_id-keyed pub/sub +
  persisted progress).
- `app/db/` — Motor client (`client.py`, collection-name constants, indexes)
  + repositories (`prompts`, `versions`, `test_cases`, runs, steps,
  reports). Docs use
  string UUID4 ids (`_id` ↔ `id` mapping in `repositories/base.py`). No raw
  Mongo access outside repositories.
- `app/api/` — JSON API under `/api` (`/api/prompts`, `/api/test-cases`,
  `/api/evaluations`, `/api/optimizations`, …); runs are created `pending`,
  executed via FastAPI `BackgroundTasks` (`background.py`), `run_id` returned
  immediately. SSE at `/api/progress/{run_id}/stream`.
- `app/web/` — Jinja2 templates + `routes.py` (server-rendered UI reusing the
  same repos/services; no business logic in routes). Prompt management lives
  at `/prompts`.

## Domain vocabulary

- **Prompt** (formerly "optimization state") — named entity with goal,
  current prompt text, linked test cases, optimizer LLM runner, and the
  latest score/summary.
- **Grader** (formerly "evaluation step") — scores one executed data entry;
  selected per test case via `grader_names`. Criteria resolution is
  **per key**: a key present in `evaluation_criteria_per_entry[i]` wins,
  other keys fall back to the dataset `evaluation_criteria`
  (see `Grader.criteria_for`).
- **Data entry** — one element of `TestCase.data`; executed and graded
  individually, the test case score is the mean over entries.
- **Prompt version** — snapshot of a superseded prompt (text + avg score),
  saved by the optimizer before an accepted iteration replaces
  `current_prompt`; browsable from the prompt page and the run's
  iterations page.
- **Optimization iteration** — the UI name for an `OptimizationStep`
  document (one loop iteration); "steps" in the UI would collide with
  evaluation steps, so pages/URLs say "iterations" (legacy `/steps` web
  URLs redirect; the JSON API keeps `/api/optimizations/{id}/steps`).

## Conventions / gotchas

- **Dependency injection everywhere**: services take repositories +
  resolver callables (name → instance for executors/graders/runners); tests
  override resolvers instead of patching.
- Route handlers get shared singletons from `app.state` (`db`,
  `progress_tracker`) via `app/api/deps.py`; tests inject mongomock through
  `create_app(database=...)`.
- Register routes with literal path segments (e.g. `/test-cases/import`,
  `/prompts/new`) **before** parameterized ones (`/test-cases/{id}`) —
  FastAPI matches in declaration order.
- `PromptEvaluation`: up to 3 strengths/weaknesses (empty lists allowed —
  don't add filler entries), non-empty reasoning, integer score 1–10.
  Aggregated scores are floats clamped to [1, 10].
- Editing a prompt's text (API or UI) intentionally resets `avg_score` and the
  summary; the next optimization run re-establishes a baseline.
- The evaluator fails fast when a selected test case has no graders or
  references an unknown grader/executor/runner name.
- Progress events: evaluator emits raw dicts (`event: executed/completed/...`);
  `ProgressTracker.normalize` maps them to canonical types. Progress hooks and
  persistence must never raise into the run.
- Sprint tracking lives in `Documents/Implementation/SPRINT.md`; the plan and
  per-task specs in `Documents/Implementation/` (historical — they predate
  the grader/prompt terminology).
