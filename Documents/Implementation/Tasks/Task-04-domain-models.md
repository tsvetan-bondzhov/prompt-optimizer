# Task 04 — Domain Models & Schemas

**Depends on:** 01
**Milestone:** Foundation

## Objective
Define all Pydantic v2 domain models used across services, persistence, and API.

## Steps
1. In `app/models/` define the models from plan §5. Suggested module split:
   - `prompt.py`: `Prompt`, `PromptResult`.
   - `test_case.py`: `TestCase` (`id`, `name`, `data: dict`, `evaluation_criteria: dict`, `created_at`).
   - `evaluation.py`: `PromptEvaluation`, `EvaluationPoint`, `EvaluationReport`, `EvaluationSummary`, `EvaluationRun`.
   - `optimization.py`: `OptimizationState`, `OptimizationRun`, `OptimizationStep`, `ImprovementContext`, `RunConfig`.
2. Enforce constraints with validators:
   - `PromptEvaluation.score`: integer, `1 <= score <= 10`.
   - `strengths` / `weaknesses`: length 1–3 (allow empty only where the goal permits; default require ≥1).
   - `reasoning`: non-empty string.
3. `RunConfig`: `target_score: float`, `max_iterations: int`, `executions_per_test_case: int` with sane defaults from settings.
4. `OptimizationRun` includes a `progress` sub-model (`executed`, `total`, `current_step`, `status`, `events: list[...]`) and `status` enum (`pending|running|completed|failed`).
5. `OptimizationStep` includes all fields from plan §5 (previous/proposed prompt, prev/new avg score, summarized reasoning, summary, test_case_ids, evaluation_report_ids, accepted, iteration_index).
6. Provide clear separation between create/update request models and stored models where the API needs it (e.g. `TestCaseCreate`).

## Files
- `app/models/{prompt,test_case,evaluation,optimization}.py`
- `app/models/__init__.py` re-exporting public models.

## Acceptance Criteria
- All models import cleanly and validate example payloads.
- Invalid `PromptEvaluation` (score 0 or 11, empty reasoning, >3 strengths) raises `ValidationError`.
- Models serialize to/from dicts compatible with the persistence layer (Task 03).
