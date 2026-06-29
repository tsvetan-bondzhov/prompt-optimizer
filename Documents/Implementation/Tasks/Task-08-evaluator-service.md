# Task 08 — Evaluator Service

**Depends on:** 03, 04, 05
**Milestone:** Engine

## Objective
Implement the Prompt Evaluator: run the ordered evaluation steps against a prompt
across all test cases × N executions, aggregate, and persist reports.

## Steps
1. `app/services/evaluator.py` — `EvaluatorService` with dependencies injected:
   repositories (reports/runs), registry resolvers (executor, steps, aggregator),
   and an optional `ProgressTracker` (Task 11).
2. Implement `run(prompt, test_cases, executions_per_test_case, run_id=None, progress=None) -> EvaluationRunResult`:
   - Resolve `steps = get_evaluation_steps()` once.
   - For each `test_case`, for each `i in range(N)`:
     - `result = await executor.execute(prompt, test_case)`.
     - For each step (sequential): `eval = await step.evaluate(result, test_case)`.
     - `point_score = aggregator.aggregate(step_evals)` (default mean).
     - Build + persist an `EvaluationReport` (date, test_case_id, prompt text,
       prompt_result, point_score, merged strengths/weaknesses/reasoning,
       per-step evaluations, run_id).
     - Emit a progress event (`executed`, `total = N * len(test_cases)`, current state).
   - Compute `avg_score = mean(point_score over all points)`.
   - Return an in-memory result object holding all points + report ids + avg_score.
3. Create an `EvaluationRun` document (status, config, report ids, avg_score) so a
   standalone evaluation is itself a viewable run.
4. Robustness: wrap step/executor calls so one failing point is recorded
   (failed report) without aborting the entire run unless configured otherwise;
   surface errors in progress.
5. Edge cases: empty test case list raises a clear `ValueError`; `N >= 1` enforced.

## Files
- `app/services/evaluator.py`

## Acceptance Criteria
- Produces exactly `num_test_cases × N` evaluation points/reports.
- `avg_score` equals the mean of all point scores.
- Per-step evaluations are persisted alongside the aggregated point score.
- Runs standalone (callable without the optimizer) and emits progress events.
