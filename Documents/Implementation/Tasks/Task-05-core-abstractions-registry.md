# Task 05 — Core Abstractions & Registry

**Depends on:** 04
**Milestone:** Foundation

## Objective
Define the abstract extension points and a registry so concrete implementations
are selected by name from configuration (Python registry approach).

## Steps
1. `app/core/interfaces.py` — abstract base classes (see plan §4):
   - `PromptExecutor.execute(prompt, test_case) -> PromptResult` (async).
   - `EvaluationStep` with a `name` attribute and `evaluate(result, test_case) -> PromptEvaluation` (async).
   - `prepare_evaluation() -> list[EvaluationStep]` — module-level callable type/Protocol that user code implements.
   - `PromptImprover.improve(ctx: ImprovementContext) -> Prompt` (async).
   - `Summarizer.summarize(evaluations) -> EvaluationSummary` (async).
   - `LLMRunner.run(system_prompt, user_prompt) -> str` (async).
   - An aggregation `Protocol` (`aggregate(step_evals) -> float`) with a default mean implementation.
2. `app/core/registry.py`:
   - A generic `register(category, name, factory)` + `resolve(category, name)`.
   - Categories: `executor`, `evaluation_prepare`, `improver`, `summarizer`, `llm_runner`, `aggregator`.
   - Resolver helpers driven by settings: `get_executor()`, `get_evaluation_steps()`,
     `get_improver()`, `get_summarizer()`, `get_llm_runner()`, `get_aggregator()`.
   - Clear error if a configured name is not registered (list available names).
3. Provide a registration entry point (e.g. `app/core/bootstrap.py` or import side
   effects in `implementations/__init__.py`) that registers built-in/reference
   implementations at startup.
4. Document how a developer adds a new implementation (covered fully in Task 16).

## Files
- `app/core/interfaces.py`
- `app/core/registry.py`
- `app/core/bootstrap.py`

## Acceptance Criteria
- Registry returns the correct implementation by configured name and raises a
  helpful error for unknown names.
- All ABCs are importable and cannot be instantiated directly.
- Default aggregator computes the mean of step scores correctly.
