# Prompt Optimizer

A modular, extensible **prompt optimization framework**. Plug in your own
prompt-execution and grading logic, then let the framework iterate on a
prompt until it best satisfies a stated goal across a set of test cases.

Two core modules:

1. **Prompt Evaluator** — runs a prompt against every test case, `N` times
   each. A test case's `data` is an **array of entries**: each entry is
   executed individually by the test case's executor and graded by the test
   case's selected **graders**; each grader returns a structured
   `PromptEvaluation` (strengths, weaknesses, reasoning, score 1–10). The
   entry scores are aggregated (default: mean) into the test case score and
   persisted as evaluation reports.
2. **Prompt Optimizer** — a feedback loop that asks an LLM for an improved
   prompt, re-evaluates it over all test cases, summarizes the results, and
   accepts the proposal only when its average score is **strictly greater**
   than the current best. It stops when the target score is reached or the
   iteration budget is exhausted.

A **FastAPI + Jinja2 web UI** manages prompts and test cases, runs standalone
evaluations and optimization loops, and shows **live progress via Server-Sent
Events**. This is an internal tool — there is no authentication.

Architecture details: [Documents/Implementation/IMPLEMENTATION_PLAN.md](Documents/Implementation/IMPLEMENTATION_PLAN.md)
(historical plan — it predates the grader/prompt terminology).
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

1. **Test cases** (`/test-cases`) — create test cases with:
   - `data`: a JSON **array** of entry objects; each entry is executed and
     graded individually (the test case score is the average over entries);
   - `evaluation criteria per data entry`: a JSON array aligned by index with
     `data`;
   - `evaluation criteria for dataset`: a JSON object used as the fallback
     when an entry has no criteria of its own;
   - **graders**: checkboxes selecting which registered graders run
     (`keyword_coverage`, `response_quality`, `json_schema`,
     `json_expected_match`, `word_count`, `model_grader`, …);
   - **executor**: radio buttons selecting how the prompt is run (`default`,
     `template`, `no_args`, `concat`, …), plus the **LLM runner** the
     executor delegates to and the LLM runner used for summarization —
     each with runner-specific options (model, effort, temperature).
   Every executor/grader shows a human-readable name with an ℹ info popup
   documenting its purpose, criteria keys, and a copy-pasteable sample.
   Bulk JSON import is supported.
2. **Prompts** (`/prompts`) — the prompt management page: create, edit, and
   delete prompts. A prompt has a **name** (shown in reports and tables), a
   goal, the current prompt text, linked test cases, and the LLM runner used
   by the optimizer. The prompt tracks the best text found so far, its
   average score, and the latest strengths/weaknesses summary. Superseded
   versions (text + average score) are kept: whenever the optimizer accepts
   an improved prompt the outgoing version is saved, and the prompt page
   lists all versions with a details link.
3. **Run a standalone evaluation** (`/evaluate`) — pick a prompt (or paste
   prompt text), test cases, and `executions per test case`; the run page
   shows live progress and links to the produced evaluation reports (date,
   test case, prompt name, result, score, strengths, weaknesses, reasoning,
   per-entry results).
4. **Run an optimization loop** (`/optimize`) — pick a prompt plus a target
   score / max iterations / executions per test case. Every iteration persists
   an optimization step (previous & proposed prompt, previous & new average
   score, summary, links to all evaluation reports) whether accepted or
   rejected. The prompt only advances on a strictly better score; each
   accepted iteration first snapshots the outgoing prompt version, and the
   run's steps page lists the versions it saved.
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
| `ACTIVE_EXECUTOR` | `default` | Default `PromptExecutor` (test cases select their own) |
| `ACTIVE_OPTIMIZER` | `claude_code` | Registry key for the `PromptOptimizer` |
| `ACTIVE_SUMMARIZER` | `default` | Registry key for the `Summarizer` |
| `ACTIVE_LLM_RUNNER` | `claude_code` | Default `LLMRunner` (test cases / prompts select their own) |
| `CLAUDE_CLI_PATH` | `claude` | Path to the Claude Code CLI |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server for the `ollama` runner |
| `OLLAMA_MODEL` | `mistral` | Model used by the `ollama` runner |
| `DEFAULT_EXECUTIONS_PER_TEST_CASE` | `1` | Default N |
| `DEFAULT_TARGET_SCORE` | `9.0` | Loop stop threshold |
| `DEFAULT_MAX_ITERATIONS` | `10` | Loop stop limit |
| `OPTIMIZER_SYSTEM_PROMPT` | built-in constant | Optimizer system prompt |
| `JSON_EVAL_ALLOW_MARKDOWN` | `false` | Let the JSON graders accept Markdown-fenced output |
| `LOG_LEVEL` | `INFO` | Logging level |

Set `ACTIVE_LLM_RUNNER=fake` for fully offline operation (deterministic echo
runner — useful for demos and development without the Claude CLI).

## Extending

Every seam is a registered implementation selected by name — per test case /
per prompt in the UI, or through the `ACTIVE_*` defaults:

- **`PromptExecutor`** — what "running the prompt" means; executes one data
  entry at a time and delegates LLM calls to the selected `LLMRunner`.
  Built-ins: `default`, `template` (placeholder rendering), `no_args`
  (prompt as-is), `concat` (prompt + serialized entry).
- **`Grader`** — your scoring logic, selected per test case. Built-ins include
  deterministic graders (keywords, response shape, word count, JSON
  schema/expected-match) and `model_grader` (LLM-as-judge configured via the
  evaluation criteria).
- **`PromptOptimizer` / `Summarizer`** — LLM-backed by default, swappable.
- **`LLMRunner`** — the LLM transport: `claude_code` (headless `claude -p`),
  `ollama` (local Ollama server), `fake` (offline echo); implement one
  interface method to add another provider.

Copy-pasteable examples for each: [docs/EXTENDING.md](docs/EXTENDING.md).

## Project layout

```
app/
├─ main.py            # FastAPI app factory + lifespan
├─ config.py          # pydantic-settings configuration
├─ models/            # Pydantic domain models
├─ core/              # ABCs + implementation registry
├─ llm/               # LLMRunner interface + Claude Code / Ollama / fake runners
├─ implementations/   # USER code (executors + graders; reference examples shipped)
├─ services/          # evaluator, optimizer, summarizer, progress tracker
├─ db/                # Motor client + repositories
├─ api/               # JSON API routes + SSE + background execution
└─ web/               # Jinja2 templates + static assets + web routes
tests/                # unit / integration / api (offline, mongomock)
docker/               # Dockerfile + docker-compose.yml
```
