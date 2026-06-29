# Task 07 — Reference Implementations

**Depends on:** 05, 06
**Milestone:** Engine

## Objective
Ship working **reference/example** implementations of every user-supplied
extension point so the framework runs end-to-end out of the box and developers
have a clear template to copy.

## Steps
1. `app/implementations/executor.py` — example `PromptExecutor`:
   - Documented placeholder showing where the user invokes their target LLM with
     `(prompt, test_case)`. Reference version can call the active `LLMRunner` or
     return a deterministic stub; clearly mark the line the user replaces.
2. `app/implementations/evaluation_steps.py` — one or more example
   `EvaluationStep`s that take `(PromptResult, TestCase)` and return a valid
   `PromptEvaluation` (`strengths`, `weaknesses`, `reasoning`, `score`).
   - **No built-in LLM call** (per decision): show how to derive the structured
     evaluation from `result.text` and `test_case.evaluation_criteria` using the
     user's own logic. Provide a simple heuristic example + clear TODO markers.
3. `app/implementations/prepare.py` — `prepare_evaluation()` returning the ordered
   list of concrete `EvaluationStep` instances; register it under
   `evaluation_prepare / "default"`.
4. `app/implementations/improver.py` — `ClaudeCodePromptImprover(PromptImprover)`:
   - Build the LLM context from `ImprovementContext` (goal, current prompt,
     strengths, weaknesses, score, reasoning) + the hard-coded, easily editable
     `IMPROVER_SYSTEM_PROMPT` constant.
   - Call the active `LLMRunner`; return the new `Prompt`.
   - Register under `improver / "claude_code"`.
5. `app/implementations/summarizer.py` — default `Summarizer` (detailed in Task 10);
   register under `summarizer / "default"`.
6. Ensure `implementations/__init__.py` imports all modules so registrations fire
   (or wire them in `core/bootstrap.py`).

## Files
- `app/implementations/{executor,evaluation_steps,prepare,improver,summarizer}.py`
- `app/implementations/__init__.py`

## Acceptance Criteria
- With reference impls + `FakeLLMRunner`, evaluator and optimizer run end-to-end.
- Every extension point has a copy-paste template with explicit TODO markers.
- `IMPROVER_SYSTEM_PROMPT` is a single, clearly-located, editable constant.
