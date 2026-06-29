# Task 10 — Summarization Component

**Depends on:** 05, 06
**Milestone:** Engine

## Objective
Condense many `PromptEvaluation`s (across all test cases × executions) into a
single `EvaluationSummary` (consolidated strengths, weaknesses, reasoning) used
to update state and to feed the next improvement step.

## Steps
1. `app/services/summarizer.py` — `SummarizerService` wrapping the active
   `Summarizer` implementation from the registry.
2. Default `Summarizer` (`app/implementations/summarizer.py`, registered `default`):
   - Compose all strengths/weaknesses/reasoning + scores into an LLM prompt and
     call the active `LLMRunner` to produce a concise structured summary.
   - Validate/parse the LLM output into `EvaluationSummary`.
3. Provide a deterministic non-LLM fallback summarizer (registered `frequency`):
   - Aggregate by frequency (top-K strengths/weaknesses) and concatenate/trim
     reasoning. Used for tests and offline mode (no external calls).
4. Keep the summary compact (configurable top-K, e.g. top 3 strengths/weaknesses)
   to fit the improver context window.

## Files
- `app/services/summarizer.py`
- `app/implementations/summarizer.py`

## Acceptance Criteria
- `summarize(points)` returns a valid `EvaluationSummary` for many inputs.
- Frequency fallback works with zero external/LLM calls.
- Output is bounded (top-K) and feeds cleanly into `ImprovementContext`.
