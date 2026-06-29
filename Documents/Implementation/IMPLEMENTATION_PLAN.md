# Prompt Optimizer Framework — Implementation Plan

## 1. Overview

This document describes the design and implementation plan for a **modular,
extensible prompt optimization framework**. The framework lets developers plug
in their own prompt-execution and prompt-evaluation logic, then automatically
iterate on a prompt until it best satisfies a stated goal across a set of test
cases.

The system has two primary modules:

1. **Prompt Evaluator** — runs an ordered list of evaluation steps against a
   `(prompt, test case)` pair. Each step returns a structured JSON
   `PromptEvaluation` object (`strengths`, `weaknesses`, `reasoning`, `score`).
2. **Prompt Optimizer** — a feedback loop that reads the current optimization
   state from the database, asks an LLM to generate an improved prompt, runs the
   evaluator over all test cases, aggregates the results, and keeps the better
   prompt. It repeats until a target score is reached or a maximum number of
   iterations is hit.

A **FastAPI + Jinja2 web UI** lets internal users manage state and test cases,
run standalone evaluations, run the optimization loop, and view detailed
reports — with **live progress** streamed via Server-Sent Events (SSE).

> This is an **internal tool**: no authentication or authorization is required.

---

## 2. Design Decisions (confirmed)

| Topic | Decision |
|-------|----------|
| Language / web framework | Python + FastAPI |
| UI rendering | Jinja2 server-rendered templates (+ HTMX/vanilla JS for SSE) |
| Long-running jobs | FastAPI `BackgroundTasks` |
| Progress reporting | Server-Sent Events (SSE) + persisted progress in DB |
| Database | MongoDB (async via **Motor**) |
| Pipeline configuration | **Python registry** of pluggable implementations |
| Evaluation LLM | **Fully user-implemented** — evaluation steps contain no built-in LLM call |
| Optimization / summarization LLM | Pluggable `LLMRunner`; default = **Claude Code headless (`-p`)** |
| Packaging / deploy | Docker + docker-compose (app + mongo) |
| Auth | None (internal tool) |

---

## 3. Architecture

### 3.1 High-level component diagram

```
                         ┌───────────────────────────────────────────┐
                         │                Web UI (Jinja2)             │
                         │  dashboard · test cases · runs · reports    │
                         └───────────────▲─────────────┬──────────────┘
                                         │ HTML/SSE     │ HTTP
                         ┌───────────────┴─────────────▼──────────────┐
                         │                FastAPI app                  │
                         │  routes · BackgroundTasks · SSE endpoints   │
                         └───┬───────────────┬───────────────┬─────────┘
                             │               │               │
                  ┌──────────▼───┐   ┌────────▼────────┐  ┌───▼──────────┐
                  │  Evaluator   │   │   Optimizer     │  │  Progress     │
                  │  Service     │◄──┤   Service       │─►│  Tracker (SSE)│
                  └──────┬───────┘   └───────┬─────────┘  └───────────────┘
                         │                   │
        ┌────────────────┼───────────────────┼──────────────────────────┐
        │   Core abstractions (registry)      │                          │
        │  PromptExecutor · EvaluationStep    │  PromptImprover           │
        │  prepare_evaluation()               │  Summarizer · LLMRunner   │
        └────────────────┬────────────────────┴──────────────┬───────────┘
                         │ user implementations               │ default impl
                  ┌──────▼─────────────┐              ┌────────▼──────────┐
                  │ implementations/   │              │ Claude Code (-p)  │
                  │ (executor, steps)  │              │ subprocess runner │
                  └────────────────────┘              └───────────────────┘
                         │
                  ┌──────▼───────────────────────────────────────────────┐
                  │                     MongoDB (Motor)                   │
                  │  test_cases · optimization_states · optimization_runs │
                  │  optimization_steps · evaluation_runs · evaluation_…  │
                  └───────────────────────────────────────────────────────┘
```

### 3.2 Layered structure

- **Domain models** (`models/`): Pydantic models shared everywhere.
- **Core abstractions** (`core/`): abstract base classes + a registry that maps
  names → concrete implementations.
- **LLM runners** (`llm/`): `LLMRunner` interface + `ClaudeCodeRunner`.
- **User implementations** (`implementations/`): concrete `PromptExecutor`,
  `EvaluationStep`s and `prepare_evaluation()` (reference examples shipped).
- **Services** (`services/`): `EvaluatorService`, `OptimizerService`,
  `SummarizerService`, `ProgressTracker`.
- **Persistence** (`db/`): Motor client + repositories.
- **API / Web** (`api/`, `web/`): routes, SSE, Jinja2 templates, static assets.

---

## 4. Core Abstractions (the extension points)

All abstractions are `abc.ABC` subclasses registered in a central registry so
the active implementation can be swapped without touching service code.

```python
# core/interfaces.py  (signatures — see task files for full detail)

class PromptExecutor(ABC):
    async def execute(self, prompt: Prompt, test_case: TestCase) -> PromptResult: ...

class EvaluationStep(ABC):
    name: str
    async def evaluate(self, result: PromptResult, test_case: TestCase) -> PromptEvaluation: ...

def prepare_evaluation() -> list[EvaluationStep]:
    """User-implemented factory returning ordered, concrete EvaluationStep instances."""

class PromptImprover(ABC):
    async def improve(self, ctx: ImprovementContext) -> Prompt: ...

class Summarizer(ABC):
    async def summarize(self, evaluations: list[PromptEvaluation]) -> EvaluationSummary: ...

class LLMRunner(ABC):
    async def run(self, system_prompt: str, user_prompt: str) -> str: ...
```

- `PromptExecutor` and `EvaluationStep`/`prepare_evaluation` are **user-supplied**
  (reference examples included). Evaluation steps **do not** ship a built-in LLM
  call — the user wires their own scoring logic.
- `PromptImprover` and `Summarizer` use a pluggable `LLMRunner`. Default runner =
  `ClaudeCodeRunner` (headless `claude -p`). Swapping to Cursor / Copilot /
  Anthropic API later means writing a new `LLMRunner` and registering it.

### 4.1 Registry

`core/registry.py` exposes a simple registry + settings-driven selection:

```python
register("executor", "default", MyExecutor)
register("improver", "claude_code", ClaudeCodePromptImprover)
...
get_executor()      # resolves the active impl from settings
get_evaluation_steps()  # calls the active prepare_evaluation()
```

Active implementations are chosen by name in `config.py` / environment variables.

---

## 5. Domain Model

| Model | Key fields |
|-------|-----------|
| `Prompt` | `text: str` (value object) |
| `TestCase` | `id`, `name`, `data: dict`, `evaluation_criteria: dict`, `created_at` |
| `PromptResult` | `text: str` (output of execution) |
| `PromptEvaluation` | `strengths: list[str]` (1–3), `weaknesses: list[str]` (1–3), `reasoning: str`, `score: int` (1–10), `step_name` |
| `EvaluationPoint` | one `(test_case × execution_index)` run: `prompt_result`, list of per-step `PromptEvaluation`, `aggregated_score` |
| `EvaluationReport` | persisted point: `date`, `test_case_id`, `prompt`, `prompt_result`, `score`, `strengths`, `weaknesses`, `reasoning`, `step_evaluations`, `run_id` |
| `EvaluationSummary` | merged `strengths`, `weaknesses`, `reasoning` across many points |
| `OptimizationState` | `goal`, `current_prompt`, `avg_score`, `test_case_ids`, `strengths`, `weaknesses`, `reasoning`, `updated_at` |
| `OptimizationRun` | a single loop invocation: `state_id`, `config` (target_score, max_iterations, executions_per_test_case), `status`, `progress`, timestamps |
| `OptimizationStep` | one iteration: `previous_prompt`, `proposed_prompt`, `previous_avg_score`, `new_avg_score`, `summarized_reasoning`, `summary` (strengths/weaknesses), `test_case_ids`, `evaluation_report_ids`, `accepted: bool`, `iteration_index` |

### 5.1 MongoDB collections

```
test_cases            test case documents
optimization_states   current best state per goal/project
optimization_runs     one document per optimization loop execution (+ progress)
optimization_steps     one document per iteration (proposed prompt + results links)
evaluation_runs        one document per evaluator invocation (standalone or loop-internal)
evaluation_reports     one document per evaluation point (linked to a run)
```

Indexes: `evaluation_reports.run_id`, `optimization_steps.run_id`,
`test_cases.created_at`, `optimization_states.goal`.

---

## 6. Module Behaviour

### 6.1 Prompt Evaluator

Inputs: a `prompt`, a list of `TestCase`s, `executions_per_test_case (N)`.

```
steps = prepare_evaluation()
for test_case in test_cases:
    for i in range(N):
        result = executor.execute(prompt, test_case)
        step_evals = [step.evaluate(result, test_case) for step in steps]   # sequential
        point_score = aggregate(step_evals)        # default: mean of step scores
        persist EvaluationReport(point)            # one report per (test_case, i)
        emit progress event
avg_score = mean(point.aggregated_score for all points)   # over N * num_test_cases points
```

- **Total evaluation points = `num_test_cases × N`** (per the goal).
- Each point aggregates its steps into a single score (default mean; aggregation
  strategy is pluggable). Per-step evaluations are also stored for traceability.
- The evaluator can run **standalone** (no optimization) from the UI.

### 6.2 Prompt Optimizer (feedback loop)

```
state = load_state(state_id)

# Edge case: first run / no baseline score yet
if state.avg_score is None or no evaluation data exists:
    baseline = evaluator.run(state.current_prompt, test_cases, N)
    state.avg_score = baseline.avg_score
    state.strengths/weaknesses/reasoning = summarizer.summarize(baseline.points)
    persist state + baseline evaluation_run

iteration = 0
while state.avg_score < target_score and iteration < max_iterations:
    proposed = improver.improve(ImprovementContext(
        goal, state.current_prompt, state.strengths, state.weaknesses,
        state.avg_score, state.reasoning, system_prompt))

    run = evaluator.run(proposed, test_cases, N)        # all reports persisted
    summary = summarizer.summarize(run.points)          # merge strengths/weaknesses/reasoning
    new_avg = run.avg_score

    accepted = new_avg > state.avg_score
    persist OptimizationStep(previous_prompt, proposed, prev_avg, new_avg,
                             summary, test_case_ids, report_ids, accepted, iteration)

    if accepted:
        state.update(current_prompt=proposed, avg_score=new_avg, summary=summary)
        persist state
    # else: keep previous best state

    iteration += 1
    emit progress event

return state
```

Key points:
- **Every proposed prompt and all pre-summarization validation results are
  always persisted**, regardless of acceptance.
- State is only updated when the new average score is strictly better.
- Stop conditions: `avg_score >= target_score` **or** `iteration >= max_iterations`.

### 6.3 Summarization

`Summarizer.summarize(points)` condenses many `PromptEvaluation`s into a single
`EvaluationSummary` (top strengths, top weaknesses, consolidated reasoning).
Default implementation uses the pluggable `LLMRunner`; a deterministic
non-LLM fallback (frequency-based aggregation) is also provided for tests/offline.

### 6.4 Progress + SSE

- A `ProgressTracker` keeps in-memory state per `run_id` and an `asyncio.Queue`
  pub/sub for subscribers; progress is **also persisted** to the run document so
  a page reload reconstructs current status.
- Each service emits events: `step_started`, `step_completed`, `iteration_done`,
  `run_completed`, including `executed / remaining / current_state` and a summary
  of each step executed so far.
- SSE endpoint streams events; the run page renders the live report.

---

## 7. Project Structure

```
prompt-optimizer/
├─ app/
│  ├─ main.py                  # FastAPI app factory + lifespan
│  ├─ config.py                # pydantic-settings configuration
│  ├─ db/
│  │  ├─ client.py             # Motor client + lifecycle + index setup
│  │  └─ repositories/         # test_cases, states, runs, steps, reports
│  ├─ models/                  # Pydantic domain models + Mongo doc schemas
│  ├─ core/
│  │  ├─ interfaces.py         # abstract base classes
│  │  └─ registry.py           # implementation registry + resolvers
│  ├─ llm/
│  │  ├─ base.py               # LLMRunner ABC
│  │  └─ claude_code.py        # ClaudeCodeRunner (headless -p)
│  ├─ implementations/         # USER code (reference examples shipped)
│  │  ├─ executor.py           # example PromptExecutor
│  │  ├─ evaluation_steps.py   # example EvaluationStep(s)
│  │  ├─ prepare.py            # prepare_evaluation()
│  │  ├─ improver.py           # ClaudeCodePromptImprover
│  │  └─ summarizer.py         # default Summarizer
│  ├─ services/
│  │  ├─ evaluator.py
│  │  ├─ optimizer.py
│  │  ├─ summarizer.py
│  │  └─ progress.py
│  ├─ api/
│  │  ├─ routes_testcases.py
│  │  ├─ routes_evaluation.py
│  │  ├─ routes_optimization.py
│  │  ├─ routes_reports.py
│  │  └─ routes_progress.py    # SSE
│  └─ web/
│     ├─ templates/            # Jinja2
│     └─ static/               # css/js
├─ tests/
├─ docker/
│  ├─ Dockerfile
│  └─ docker-compose.yml
├─ pyproject.toml (or requirements.txt)
├─ .env.example
├─ AGENTS.md
└─ README.md
```

---

## 8. Configuration

`app/config.py` (pydantic-settings), overridable via env / `.env`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `MONGO_URI` | `mongodb://mongo:27017` | Mongo connection |
| `MONGO_DB` | `prompt_optimizer` | DB name |
| `ACTIVE_EXECUTOR` | `default` | Registry key for `PromptExecutor` |
| `ACTIVE_IMPROVER` | `claude_code` | Registry key for `PromptImprover` |
| `ACTIVE_SUMMARIZER` | `default` | Registry key for `Summarizer` |
| `ACTIVE_LLM_RUNNER` | `claude_code` | Registry key for `LLMRunner` |
| `CLAUDE_CLI_PATH` | `claude` | Path to Claude Code CLI |
| `DEFAULT_EXECUTIONS_PER_TEST_CASE` | `1` | N |
| `DEFAULT_TARGET_SCORE` | `9.0` | Loop stop threshold |
| `DEFAULT_MAX_ITERATIONS` | `10` | Loop stop limit |
| `IMPROVER_SYSTEM_PROMPT` | (hard-coded default, easily editable constant) | Optimizer system prompt |

---

## 9. Edge Cases & Risks

- **First optimization run with no baseline:** run the evaluator once before the
  loop to establish `avg_score` + summary (handled in §6.2).
- **No test cases:** validation/optimization endpoints reject with a clear error.
- **Tie scores:** new prompt must be **strictly greater** to be accepted.
- **LLM/CLI failure:** improver/runner raises a typed error; the run is marked
  `failed`, progress event emitted, partial results preserved.
- **Malformed evaluation JSON:** evaluation steps must return validated
  `PromptEvaluation`; invalid output raises and is surfaced in the report.
- **Long runs & concurrency:** BackgroundTasks per run; `ProgressTracker` keyed
  by `run_id`; SSE clients can reconnect and rebuild from persisted progress.
- **Score bounds:** scores clamped/validated to integer 1–10.

---

## 10. Testing Strategy

- **Unit:** registry resolution, aggregation math, summarizer fallback, model
  validation, optimizer accept/reject logic.
- **Integration:** evaluator + optimizer end-to-end against `mongomock`/test Mongo
  with a `FakeExecutor`, `FakeEvaluationStep`, and `FakeLLMRunner` (deterministic).
- **API:** FastAPI `TestClient` for CRUD + run endpoints + SSE smoke test.
- No real LLM calls in CI; Claude runner is mocked.

---

## 11. Milestones

1. **Foundation** — Tasks 01–05 (scaffolding, docker, db, models, core abstractions).
2. **Engine** — Tasks 06–10 (LLM runner, reference impls, evaluator, optimizer, summarizer).
3. **Surface** — Tasks 11–14 (progress/SSE, app wiring, API routes, web UI).
4. **Hardening** — Tasks 15–16 (tests, documentation).

---

## 12. Task Index

| # | Task | Depends on |
|---|------|-----------|
| 01 | [Project scaffolding & configuration](Tasks/Task-01-project-scaffolding.md) | — |
| 02 | [Docker & docker-compose](Tasks/Task-02-docker-compose.md) | 01 |
| 03 | [MongoDB persistence layer](Tasks/Task-03-mongodb-persistence.md) | 01 |
| 04 | [Domain models & schemas](Tasks/Task-04-domain-models.md) | 01 |
| 05 | [Core abstractions & registry](Tasks/Task-05-core-abstractions-registry.md) | 04 |
| 06 | [LLM runner + Claude Code headless](Tasks/Task-06-llm-runner-claude-code.md) | 05 |
| 07 | [Reference implementations](Tasks/Task-07-reference-implementations.md) | 05, 06 |
| 08 | [Evaluator service](Tasks/Task-08-evaluator-service.md) | 03, 04, 05 |
| 09 | [Optimizer service + feedback loop](Tasks/Task-09-optimizer-service.md) | 08, 10 |
| 10 | [Summarization component](Tasks/Task-10-summarization.md) | 05, 06 |
| 11 | [Progress tracking + SSE](Tasks/Task-11-progress-tracking-sse.md) | 03 |
| 12 | [FastAPI app & background orchestration](Tasks/Task-12-fastapi-app-orchestration.md) | 08, 09, 11 |
| 13 | [API routes](Tasks/Task-13-api-routes.md) | 12 |
| 14 | [Web UI (Jinja2 + SSE)](Tasks/Task-14-web-ui.md) | 13 |
| 15 | [Testing](Tasks/Task-15-testing.md) | 08, 09, 13 |
| 16 | [Documentation & developer guide](Tasks/Task-16-documentation.md) | all |

Each task file contains: objective, dependencies, detailed steps, files to
create/modify, interfaces, and acceptance criteria.
