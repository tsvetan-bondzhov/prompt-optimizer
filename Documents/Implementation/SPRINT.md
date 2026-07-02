# Sprint — Prompt Optimizer Framework

Orchestrated implementation of `IMPLEMENTATION_PLAN.md`. Each task is implemented
by an implementation subagent and then code-reviewed by a separate review subagent.

## State legend
- `none` — not started
- `in_progress` — implementation subagent working
- `for_review` — implementation done, awaiting / in code review
- `done` — implemented and review passed

## Execution order
Topologically sorted by declared dependencies:
`01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 10 → 09 → 11 → 12 → 13 → 14 → 15 → 16`
(Task 09 depends on Task 10, so 10 precedes 09.)

## Task board

| # | Task | Milestone | Depends on | State |
|---|------|-----------|-----------|-------|
| 01 | Project Scaffolding & Configuration | Foundation | none | done |
| 02 | Docker & docker-compose | Foundation | 01 | done |
| 03 | MongoDB Persistence | Foundation | 01 | done |
| 04 | Domain Models | Foundation | 01 | done |
| 05 | Core Abstractions & Registry | Foundation | 04 | done |
| 06 | LLM Runner (Claude Code) | Engine | 05 | done |
| 07 | Reference Implementations | Engine | 05, 06 | done |
| 08 | Evaluator Service | Engine | 03, 04, 05 | done |
| 10 | Summarization | Engine | 05, 06 | done |
| 09 | Optimizer Service | Engine | 08, 10 | done |
| 11 | Progress Tracking (SSE) | Surface | 03 | done |
| 12 | FastAPI App Orchestration | Surface | 08, 09, 11 | done |
| 13 | API Routes | Surface | 12 | done |
| 14 | Web UI | Surface | 13 | done |
| 15 | Testing | Hardening | 08, 09, 13 | done |
| 16 | Documentation | Hardening | all | done |

## Notes / Review log
- **Task 01** — PASS. Scaffolding, `pyproject.toml`, `app/config.py` (all §8 settings + cached `get_settings()`), `.env.example`, `app/logging_config.py`, `.gitignore`. Verified import + config load in venv. Note: full dep install not run end-to-end.
- **Task 02** — PASS. `docker/Dockerfile` (python:3.12-slim), `docker/docker-compose.yml` (app + mongo:7 w/ healthcheck + named volume), `.dockerignore`. `docker compose config` validates (exit 0). No secrets baked in; MONGO_URI aligns with config default. `app/main.py` referenced by CMD comes in a later task.
- **Task 03** — PASS. `app/db/client.py` (Motor lifecycle + `ensure_indexes` for §5.1 indexes), repositories for all 6 collections (`base.py`, `test_cases`, `states`, `runs`, `steps`, `reports`). String UUID4 `_id`↔`id` mapping. Smoke-tested with mongomock-motor. Repos use dicts (models arrive in Task 04).
- **Task 04** — PASS. Pydantic v2 models under `app/models/` (`common`, `prompt`, `test_case`, `evaluation`, `optimization`). All §5 models w/ constraints (score 1-10, strengths/weaknesses 1-3, RunStatus enum, RunConfig defaults from settings). Field names align with repos. Verified valid/invalid instantiation + JSON round-trip.
- **Task 05** — PASS. `app/core/interfaces.py` (ABCs: PromptExecutor/EvaluationStep/PromptImprover/Summarizer/LLMRunner + PrepareEvaluation/Aggregator protocols, mean_aggregator), `app/core/registry.py` (register/resolve + settings-driven get_* with clear errors), `app/core/bootstrap.py`. Concrete impls correctly deferred. Verified ABCs non-instantiable + resolver behavior.
- **Task 06** — PASS. `app/llm/base.py` (LLMRunnerError, compose_prompt), `app/llm/claude_code.py` (`ClaudeCodeRunner` — async `claude -p` via create_subprocess_exec, timeout/non-zero/missing-binary handling), `app/llm/fake.py` (`FakeLLMRunner`). Registered `claude_code`+`fake` in `register_builtins()`. Verified resolution with mocked subprocess.
- **Task 07** — PASS. `app/implementations/executor.py` (`ReferencePromptExecutor` via get_llm_runner, `# >>> USER` markers), `evaluation_steps.py` (`KeywordCoverageStep`, `ResponseQualityStep` — deterministic, no LLM), `prepare.py` (`prepare_evaluation()`). Registered under `default` via `register_builtins()`. End-to-end verified with FakeLLMRunner. NOTE: improver/summarizer steps in this task file intentionally deferred to Task 10.
- **Task 08** — PASS. `app/services/evaluator.py` (`EvaluatorService`, `EvaluationRunResult`). Produces exactly `N×len(test_cases)` reports, mean `avg_score`, per-step evals persisted, standalone `EvaluationRun` lifecycle, progress hook (sync/async), empty/`N<1` ValueErrors, per-point failure isolation (failed report + error surfaced). Imports clean in venv.
- **Task 10** — PASS. `app/services/summarizer.py` (`SummarizerService`, accepts `EvaluationPoint`|`PromptEvaluation`, flattens `step_evaluations`), `app/implementations/summarizer.py` (`LLMSummarizer`=`default` w/ tolerant JSON parse + frequency fallback; `FrequencySummarizer`=`frequency`, deterministic, zero LLM, top-K=3). Registered in `register_builtins()`. Verified: frequency 0 LLM calls, bounded output, default falls back on parse failure.
- **Task 09** — PASS. `app/services/optimizer.py` (`OptimizerService.optimize(state_id, config)`): baseline-once when `avg_score is None` (evaluator `run_id=None` → standalone EvaluationRun), iterations call evaluator with optimization `run_id` (reports link, no dup run), summarize→`accepted = new_avg > prev` (strict), persists an `OptimizationStep` every iteration (accepted+rejected) with full fields + report links, state updates only on acceptance, stops at target/max, run marked completed/failed w/ error event. Added required `app/implementations/improver.py` (`LLMImprover`, registered `claude_code`+`default`) since no improver existed; wired in `register_builtins()`. Verified baseline-once/strict-greater/per-iteration persistence/stop conditions with fakes.
- **Task 12** — PASS. `app/main.py` (`create_app(database=None)` factory + lifespan: `register_builtins()`, Motor connect + `ensure_indexes` (non-fatal w/ 5s server-selection timeout), singleton `ProgressTracker` persisting progress to owning run doc (optimization→evaluation fallback), shared handles on `app.state`; conditional static mount; `/health`). `app/api/deps.py` (repo + service providers off `app.state.db`/`progress_tracker`). `app/api/background.py` (`execute_evaluation_run` — pending→running→completed/failed + error event; `execute_optimization_run` — delegates status to OptimizerService, never raises). `OptimizerService.optimize` gained optional pre-created `run_id`. Verified: startup/shutdown + `/health` with mongomock; uvicorn starts and serves with Mongo down.
- **Task 13** — PASS. Six routers under `/api` wired via `main._include_routers`: `routes_testcases` (CRUD + bulk `/import`), `routes_state` (CRUD; prompt edit resets score/summary; test-case id validation), `routes_evaluation` (`POST` pending-run + BackgroundTasks → `run_id`; prompt/test-cases from body or state; `GET /{id}` + `/reports`), `routes_optimization` (`POST` → `run_id` w/ pre-created run; `GET /{id}` + `/steps`), `routes_reports` (report/step detail + filtered list), `routes_progress` (SSE: subscribe-then-snapshot, persisted-progress fallback, closes on terminal). Smoke-verified full flow with FakeLLMRunner + mongomock: CRUD, 2 reports @N=2, 2 optimization steps w/ report links, SSE snapshot.
- **Task 14** — PASS. `app/web/routes.py` (server-rendered pages reusing repos/services + background executors; JSON-field form parsing w/ 400s; prompt edit resets score; unified diff on step detail) + 13 templates (base/nav, dashboard, test_cases + form + bulk import, state + form, run_evaluation, run_optimization, progress, evaluation_reports + detail, optimization_steps + detail) + `static/styles.css` (status pills, accepted/rejected row coloring, score highlights) + `static/progress.js` (EventSource: snapshot rebuild on reload → live events → closes on terminal). Fixed route-order bug (`/test-cases/import` before `/{id}`). Smoke-verified every page + full form flows (create/edit/import/evaluate/optimize/reports/steps/static) via TestClient.
- **Task 15** — PASS. 43 tests, 0.4s, zero LLM/network. `tests/fakes.py` (FakeExecutor, scripted FakeEvaluationStep, FailingEvaluationStep, FakeImprover, FakeSummarizer), `tests/conftest.py` (fresh mongomock db per test; autouse fixture shadows active registry names with fakes; full-app TestClient). Unit: registry resolution/unknown-name errors, model bounds (score 1–10, strengths/weaknesses 1–3, RunConfig), mean aggregator, FrequencySummarizer ranking/bounds. Integration: evaluator N×cases report count + avg + per-point failure isolation + progress hook; optimizer baseline-once, strict-greater accept (tie rejected), step persisted per iteration incl. rejected w/ report links, stops at target/max, state untouched on reject. API: test case + state CRUD (prompt edit resets score), run-start returns run_id w/ completed background execution, report/step field coverage, SSE snapshot smoke + 404.
- **Task 16** — PASS. `README.md` rewritten (overview, Docker + local quick start, UI usage guide, full §8 config table, offline mode, project layout, links to plan + extension guide). `docs/EXTENDING.md` (three-step register pattern + copy-pasteable examples for PromptExecutor, EvaluationStep/prepare_evaluation, PromptImprover/Summarizer, new LLMRunner incl. Anthropic API swap path, custom aggregator, IMPROVER_SYSTEM_PROMPT location, testing guidance). `AGENTS.md` (canonical run/test/docker/install commands, architecture summary, conventions/gotchas incl. route-ordering and strict-acceptance rules).
- **Task 11** — PASS. `app/services/progress.py` (`ProgressTracker`, `ProgressState`, `ProgressEvent`/`ProgressEventType`). Per-`run_id` pub/sub via `asyncio.Queue` (multi-subscriber), `snapshot()`, `stream()` (terminates on `run_completed`), bounded buffer (max_events=200), `make_hook()` ProgressHook-compatible w/ evaluator-dict normalization (`executed→step_completed`, `completed→run_completed`, `error→error`). Persists via injected `OptimizationRunRepository.update_progress` or callback; graceful no-op + error-safe. Verified multi-subscriber + persistence paths.
