# Prompt Optimizer

A modular, extensible **prompt optimization framework**. Plug in your own
prompt-execution and prompt-evaluation logic, then let the framework iterate on
a prompt until it best satisfies a stated goal across a set of test cases.

Two core modules:

1. **Prompt Evaluator** — runs an ordered list of user-supplied evaluation
   steps against every `(prompt, test case)` pair, `N` times each. Each step
   returns a structured `PromptEvaluation` (strengths, weaknesses, reasoning,
   score 1–10); per-point scores are aggregated (default: mean) and persisted
   as evaluation reports.
2. **Prompt Optimizer** — a feedback loop that asks an LLM for an improved
   prompt, re-evaluates it over all test cases, summarizes the results, and
   accepts the proposal only when its average score is **strictly greater**
   than the current best. It stops when the target score is reached or the
   iteration budget is exhausted.

A **FastAPI + Jinja2 web UI** manages states and test cases, runs standalone
evaluations and optimization loops, and shows **live progress via Server-Sent
Events**. This is an internal tool — there is no authentication.

Architecture details: [Documents/Implementation/IMPLEMENTATION_PLAN.md](Documents/Implementation/IMPLEMENTATION_PLAN.md).
Extension guide: [docs/EXTENDING.md](docs/EXTENDING.md).

## Quick start

### Docker (app + MongoDB)

```bash
docker compose -f docker/docker-compose.yml up --build
```

Open http://localhost:8000. MongoDB data persists in a named volume.

### Local development

Requires Python 3.11+ and a reachable MongoDB.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows (source .venv/bin/activate on Unix)
pip install -e .[dev]
copy .env.example .env          # then set MONGO_URI=mongodb://localhost:27017
uvicorn app.main:app --reload
```

### Tests

```bash
pytest
```

The suite runs entirely offline (mongomock + deterministic fakes; no LLM calls).

## Using the UI

1. **Test cases** (`/test-cases`) — create test cases with a `data` JSON object
   (inputs handed to your executor) and an `evaluation_criteria` JSON object
   (whatever your evaluation steps need to score a result). Bulk JSON import is
   supported.
2. **State** (`/states/new`) — create an optimization state: the goal, the
   current prompt, and the linked test cases. The state tracks the best prompt
   found so far, its average score, and the latest strengths/weaknesses
   summary.
3. **Run a standalone evaluation** (`/evaluate`) — pick a prompt (or a state's
   current prompt), test cases, and `executions per test case`; the run page
   shows live progress and links to the produced evaluation reports (date, test
   case, prompt, result, score, strengths, weaknesses, reasoning).
4. **Run an optimization loop** (`/optimize`) — pick a state plus a target
   score / max iterations / executions per test case. Every iteration persists
   an optimization step (previous & proposed prompt, previous & new average
   score, summary, links to all evaluation reports) whether accepted or
   rejected. The state only advances on a strictly better score.
5. **Progress** (`/runs/{run_id}`) — live SSE progress; reloading the page
   rebuilds the report from persisted progress.

Everything is also available as a JSON API under `/api` (see `/docs` for the
OpenAPI UI).

## Configuration

Settings load from environment variables or `.env`
(see [.env.example](.env.example)):

| Setting | Default | Purpose |
|---------|---------|---------|
| `MONGO_URI` | `mongodb://mongo:27017` | Mongo connection |
| `MONGO_DB` | `prompt_optimizer` | Database name |
| `ACTIVE_EXECUTOR` | `default` | Registry key for the `PromptExecutor` |
| `ACTIVE_IMPROVER` | `claude_code` | Registry key for the `PromptImprover` |
| `ACTIVE_SUMMARIZER` | `default` | Registry key for the `Summarizer` |
| `ACTIVE_LLM_RUNNER` | `claude_code` | Registry key for the `LLMRunner` |
| `CLAUDE_CLI_PATH` | `claude` | Path to the Claude Code CLI |
| `DEFAULT_EXECUTIONS_PER_TEST_CASE` | `1` | Default N |
| `DEFAULT_TARGET_SCORE` | `9.0` | Loop stop threshold |
| `DEFAULT_MAX_ITERATIONS` | `10` | Loop stop limit |
| `IMPROVER_SYSTEM_PROMPT` | built-in constant | Optimizer system prompt |
| `LOG_LEVEL` | `INFO` | Logging level |

Set `ACTIVE_LLM_RUNNER=fake` for fully offline operation (deterministic echo
runner — useful for demos and development without the Claude CLI).

## Extending

Every seam is a registered implementation selected by name through the
`ACTIVE_*` settings:

- **`PromptExecutor`** — what "running the prompt" means for your use case.
- **`EvaluationStep` + `prepare_evaluation()`** — your scoring logic (no
  built-in LLM call; you own it).
- **`PromptImprover` / `Summarizer`** — LLM-backed by default, swappable.
- **`LLMRunner`** — the default runs Claude Code headless (`claude -p`);
  implement one interface method to switch to another provider.

Copy-pasteable examples for each: [docs/EXTENDING.md](docs/EXTENDING.md).

## Project layout

```
app/
├─ main.py            # FastAPI app factory + lifespan
├─ config.py          # pydantic-settings configuration
├─ models/            # Pydantic domain models
├─ core/              # ABCs + implementation registry
├─ llm/               # LLMRunner interface + Claude Code / fake runners
├─ implementations/   # USER code (reference examples shipped)
├─ services/          # evaluator, optimizer, summarizer, progress tracker
├─ db/                # Motor client + repositories
├─ api/               # JSON API routes + SSE + background execution
└─ web/               # Jinja2 templates + static assets + web routes
tests/                # unit / integration / api (offline, mongomock)
docker/               # Dockerfile + docker-compose.yml
```
