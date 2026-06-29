# Task 09 — Optimizer Service & Feedback Loop

**Depends on:** 08, 10
**Milestone:** Engine

## Objective
Implement the optimization feedback loop described in plan §6.2, including the
first-run baseline edge case and full persistence of every iteration.

## Steps
1. `app/services/optimizer.py` — `OptimizerService` with injected dependencies:
   `EvaluatorService`, `SummarizerService`, registry improver, repositories
   (states/runs/steps/reports), `ProgressTracker`.
2. Implement `optimize(state_id, config: RunConfig) -> OptimizationState`:
   - Load `OptimizationState` and its test cases.
   - Create an `OptimizationRun` (status `running`, total iterations target, progress init).
   - **Baseline edge case:** if `state.avg_score is None` or no evaluation data
     exists, run the evaluator once on the current prompt, set
     `state.avg_score` + summary, persist baseline `EvaluationRun`, emit progress.
   - Loop while `state.avg_score < target_score` and `iteration < max_iterations`:
     1. `proposed = await improver.improve(ImprovementContext(goal, current_prompt, strengths, weaknesses, avg_score, reasoning, system_prompt))`.
     2. `eval_result = await evaluator.run(proposed, test_cases, N, run_id, progress)` — persists all reports (pre-summarization results).
     3. `summary = await summarizer.summarize(eval_result.points)`.
     4. `accepted = eval_result.avg_score > state.avg_score` (strictly greater).
     5. Persist an `OptimizationStep`: previous_prompt, proposed_prompt,
        previous_avg_score, new_avg_score, summarized_reasoning, summary,
        test_case_ids, evaluation_report_ids, accepted, iteration_index.
     6. If accepted: update + persist `OptimizationState`
        (current_prompt, avg_score, strengths/weaknesses/reasoning from summary).
        Else: leave the previous best state unchanged.
     7. Emit `iteration_done` progress event; increment iteration.
   - Mark run `completed` (or `failed` on exception) and emit `run_completed`.
3. Always persist proposed prompt + all validation results even when rejected.
4. Handle improver/LLM failures: mark run failed, persist partial results, emit error event.

## Files
- `app/services/optimizer.py`

## Acceptance Criteria
- First run with no baseline triggers exactly one baseline evaluation before iterating.
- State updates only when the new average score is strictly greater.
- Every iteration persists an `OptimizationStep` with all required fields + report links, accepted or not.
- Loop stops at target score or max iterations; final state returned.
