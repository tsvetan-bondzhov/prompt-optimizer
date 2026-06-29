# Task 15 — Testing

**Depends on:** 08, 09, 13
**Milestone:** Hardening

## Objective
Provide automated tests covering core logic, services, and API — with no real
LLM calls.

## Steps
1. Test infra:
   - `pytest`, `pytest-asyncio`, `httpx` (FastAPI `TestClient`/`AsyncClient`).
   - MongoDB for tests: `mongomock-motor` or a disposable Mongo container; a
     `conftest.py` fixture provides a clean database per test.
   - Register test doubles: `FakeLLMRunner`, `FakeExecutor`, deterministic
     `FakeEvaluationStep` (returns scripted `PromptEvaluation`s).
2. Unit tests:
   - Registry resolution + unknown-name error.
   - Aggregator mean; score validation bounds; model validators.
   - Summarizer frequency fallback.
   - Optimizer accept/reject decision (strictly-greater rule) and state update.
3. Integration tests:
   - Evaluator produces exactly `num_test_cases × N` reports and correct avg.
   - Optimizer first-run baseline path (no prior score → one baseline eval).
   - Optimizer loop persists an `OptimizationStep` per iteration (accepted &
     rejected) with report links; stops at target score and at max iterations.
4. API tests:
   - Test case CRUD; start evaluation/optimization returns `run_id`.
   - Report/step listing returns required fields.
   - SSE endpoint smoke test (connect, receive snapshot/event).
5. Add a test command to docs (Task 16) and optionally CI config.

## Files
- `tests/conftest.py`
- `tests/unit/test_*.py`
- `tests/integration/test_evaluator.py`, `tests/integration/test_optimizer.py`
- `tests/api/test_*.py`
- `tests/fakes.py` (shared test doubles)

## Acceptance Criteria
- `pytest` passes with no network/LLM access.
- Evaluator point-count and optimizer accept/reject + baseline behaviours are covered.
- API CRUD and run-start endpoints are tested.
