"""Prompt Optimizer service & feedback loop (Task 09).

The :class:`OptimizerService` drives the optimization feedback loop described in
implementation plan §6.2. Given an :class:`OptimizationState` (the current best
prompt for a goal) and a :class:`RunConfig`, it iteratively asks a
:class:`~app.core.interfaces.PromptImprover` for a better prompt, re-evaluates it
with the :class:`~app.services.evaluator.EvaluatorService`, summarizes the
results with the :class:`~app.services.summarizer.SummarizerService`, and accepts
the proposal only when its average score is **strictly greater** than the
current best.

It mirrors :class:`EvaluatorService`'s design: every collaborator (evaluator,
summarizer, improver, repositories, progress tracker) is injected so nothing is
hardcoded and tests can swap in fakes. The improver is resolved through
:func:`app.core.registry.get_improver` by default.

Key behaviours (plan §6.2 / §9):

* **First-run baseline:** when ``state.avg_score`` is ``None`` the evaluator runs
  exactly once on the current prompt to establish a baseline score + summary;
  that baseline is persisted as its own viewable :class:`EvaluationRun`.
* **Strict acceptance:** the persisted state advances only when a proposal scores
  strictly higher than the current best.
* **Full persistence:** every iteration persists an :class:`OptimizationStep`
  (proposed prompt + all report links), accepted or not. The evaluator persists
  all pre-summarization reports linked to the owning optimization run.
* **Failure handling:** improver/LLM/evaluator failures mark the run ``failed``,
  persist partial results, emit an ``error`` progress event, and re-raise.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional

from app.config import get_settings
from app.core.registry import get_improver
from app.core.interfaces import PromptImprover
from app.db.repositories.reports import EvaluationReportRepository
from app.db.repositories.runs import OptimizationRunRepository
from app.db.repositories.states import OptimizationStateRepository
from app.db.repositories.steps import OptimizationStepRepository
from app.db.repositories.test_cases import TestCaseRepository
from app.models import (
    EvaluationSummary,
    ImprovementContext,
    OptimizationRun,
    OptimizationState,
    OptimizationStep,
    Prompt,
    RunConfig,
    RunProgress,
    RunStatus,
    TestCase,
)
from app.services.evaluator import EvaluatorService
from app.services.progress import ProgressTracker
from app.services.summarizer import SummarizerService

__all__ = ["OptimizerService"]

logger = logging.getLogger(__name__)

# Resolver callable returning the active improver (defaults to the registry
# helper, overridable for tests).
ImproverResolver = Callable[[], PromptImprover]


class OptimizerService:
    """Run the optimization feedback loop for a stored optimization state."""

    def __init__(
        self,
        evaluator: EvaluatorService,
        summarizer: SummarizerService,
        state_repository: OptimizationStateRepository,
        run_repository: OptimizationRunRepository,
        step_repository: OptimizationStepRepository,
        test_case_repository: TestCaseRepository,
        *,
        report_repository: Optional[EvaluationReportRepository] = None,
        improver_resolver: ImproverResolver = get_improver,
        progress: Optional[ProgressTracker] = None,
    ) -> None:
        """:param evaluator: Evaluates a prompt across test cases (Task 08).
        :param summarizer: Condenses evaluation points into a summary (Task 10).
        :param state_repository: Loads/persists the best :class:`OptimizationState`.
        :param run_repository: Creates/updates the :class:`OptimizationRun`.
        :param step_repository: Persists one :class:`OptimizationStep` per iteration.
        :param test_case_repository: Resolves ``state.test_case_ids`` to test cases.
        :param report_repository: Optional reports repo (reports are persisted by
            the evaluator; injected for API completeness / future use).
        :param improver_resolver: Returns the active :class:`PromptImprover`.
        :param progress: Optional :class:`ProgressTracker` for live events.
        """

        self._evaluator = evaluator
        self._summarizer = summarizer
        self._states = state_repository
        self._runs = run_repository
        self._steps = step_repository
        self._test_cases = test_case_repository
        self._reports = report_repository
        self._improver_resolver = improver_resolver
        self._progress = progress

    async def optimize(
        self, state_id: str, config: RunConfig
    ) -> OptimizationState:
        """Run the optimization loop for ``state_id`` and return the final state.

        Implements the plan §6.2 loop: optional first-run baseline, then improve
        / evaluate / summarize / (strictly) accept until the target score is met
        or the iteration budget is exhausted. Every iteration persists an
        :class:`OptimizationStep`; the best :class:`OptimizationState` advances
        only on a strictly greater score.

        :param state_id: Id of the :class:`OptimizationState` to optimize.
        :param config: Tunable run parameters (target/iterations/executions).
        :returns: The final (possibly updated) :class:`OptimizationState`.
        :raises ValueError: If the state is not found or has no test cases.
        :raises Exception: Re-raises improver/evaluator failures after marking the
            run failed and persisting partial results.
        """

        state = await self._load_state(state_id)
        test_cases = await self._load_test_cases(state)

        run = await self._create_run(state_id, config)
        run_id = run.id
        hook = self._progress.make_hook(run_id) if self._progress else None

        try:
            # --- Baseline edge case (exactly one extra evaluation) -----------
            if state.avg_score is None:
                await self._establish_baseline(state, test_cases, config, hook)

            # --- Improvement loop --------------------------------------------
            iteration = 0
            while (
                state.avg_score is not None
                and state.avg_score < config.target_score
                and iteration < config.max_iterations
            ):
                await self._run_iteration(
                    state=state,
                    test_cases=test_cases,
                    config=config,
                    run_id=run_id,
                    iteration=iteration,
                    hook=hook,
                )
                iteration += 1
                await self._emit(
                    run_id,
                    {
                        "event": "iteration_done",
                        "current_step": f"iteration {iteration}",
                        "executed": iteration,
                        "total": config.max_iterations,
                        "avg_score": state.avg_score,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - mark failed + persist partials
            logger.exception("Optimization run %s failed", run_id)
            await self._runs.update(
                run_id, {"status": RunStatus.FAILED.value, "error": str(exc)}
            )
            await self._emit(
                run_id,
                {"event": "error", "error": str(exc), "current_step": "failed"},
            )
            raise

        await self._runs.update_status(run_id, RunStatus.COMPLETED.value)
        await self._emit(
            run_id,
            {
                "event": "run_completed",
                "current_step": "completed",
                "avg_score": state.avg_score,
            },
        )
        return state

    # -- loading helpers ------------------------------------------------------

    async def _load_state(self, state_id: str) -> OptimizationState:
        """Load and validate the :class:`OptimizationState` for ``state_id``."""

        doc = await self._states.get(state_id)
        if doc is None:
            raise ValueError(f"OptimizationState {state_id!r} not found.")
        return OptimizationState.model_validate(doc)

    async def _load_test_cases(
        self, state: OptimizationState
    ) -> list[TestCase]:
        """Resolve ``state.test_case_ids`` into :class:`TestCase` models."""

        if not state.test_case_ids:
            raise ValueError(
                f"OptimizationState {state.id!r} has no test cases to optimize "
                "against."
            )
        docs = await self._test_cases.list_by_ids(state.test_case_ids)
        if not docs:
            raise ValueError(
                f"None of the test cases referenced by state {state.id!r} exist."
            )
        # Preserve the state's declared ordering for deterministic evaluation.
        by_id = {doc["id"]: doc for doc in docs}
        ordered = [by_id[tcid] for tcid in state.test_case_ids if tcid in by_id]
        return [TestCase.model_validate(doc) for doc in ordered]

    async def _create_run(
        self, state_id: str, config: RunConfig
    ) -> OptimizationRun:
        """Create and persist a fresh ``running`` :class:`OptimizationRun`."""

        run = OptimizationRun(
            state_id=state_id,
            config=config,
            status=RunStatus.RUNNING,
            progress=RunProgress(
                total=config.max_iterations,
                status=RunStatus.RUNNING,
            ),
        )
        await self._runs.create(run.model_dump())
        return run

    # -- loop building blocks -------------------------------------------------

    async def _establish_baseline(
        self,
        state: OptimizationState,
        test_cases: list[TestCase],
        config: RunConfig,
        hook: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Run exactly one baseline evaluation and fold it into ``state``.

        The baseline evaluation creates its own standalone, viewable
        :class:`EvaluationRun` (``run_id=None``), so it is persisted and visible
        independently of the optimization run.
        """

        baseline = await self._evaluator.run(
            Prompt(text=state.current_prompt),
            test_cases,
            config.executions_per_test_case,
            run_id=None,
            progress=hook,
        )
        summary = await self._summarizer.summarize(baseline.points)
        self._apply_summary(state, baseline.avg_score, summary)
        await self._persist_state(state)

    async def _run_iteration(
        self,
        *,
        state: OptimizationState,
        test_cases: list[TestCase],
        config: RunConfig,
        run_id: str,
        iteration: int,
        hook: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Run a single improve / evaluate / summarize / accept iteration."""

        previous_prompt = state.current_prompt
        previous_avg = state.avg_score

        # 1. Propose an improved prompt from the current context.
        ctx = ImprovementContext(
            goal=state.goal,
            current_prompt=state.current_prompt,
            strengths=state.strengths,
            weaknesses=state.weaknesses,
            avg_score=state.avg_score,
            reasoning=state.reasoning,
            system_prompt=get_settings().IMPROVER_SYSTEM_PROMPT,
        )
        improver = self._improver_resolver()
        proposed = await improver.improve(ctx)

        # 2. Evaluate it, linking all reports to the owning optimization run.
        eval_result = await self._evaluator.run(
            proposed,
            test_cases,
            config.executions_per_test_case,
            run_id=run_id,
            progress=hook,
        )

        # 3. Summarize and decide acceptance (strictly greater).
        summary = await self._summarizer.summarize(eval_result.points)
        new_avg = eval_result.avg_score
        accepted = previous_avg is not None and new_avg > previous_avg

        # 4. Persist the step regardless of acceptance (full traceability).
        step = OptimizationStep(
            run_id=run_id,
            iteration_index=iteration,
            previous_prompt=previous_prompt,
            proposed_prompt=proposed.text,
            previous_avg_score=previous_avg,
            new_avg_score=new_avg,
            summarized_reasoning=summary.reasoning,
            summary=summary,
            test_case_ids=[tc.id for tc in test_cases],
            evaluation_report_ids=eval_result.report_ids,
            accepted=accepted,
        )
        await self._steps.create(step.model_dump())

        # 5. Advance the best state only on a strictly better score.
        if accepted:
            self._apply_summary(state, new_avg, summary, current_prompt=proposed.text)
            await self._persist_state(state)

    # -- state mutation helpers ----------------------------------------------

    @staticmethod
    def _apply_summary(
        state: OptimizationState,
        avg_score: float,
        summary: EvaluationSummary,
        *,
        current_prompt: Optional[str] = None,
    ) -> None:
        """Fold an evaluation summary + score into ``state`` (in place)."""

        if current_prompt is not None:
            state.current_prompt = current_prompt
        state.avg_score = avg_score
        state.strengths = summary.strengths
        state.weaknesses = summary.weaknesses
        state.reasoning = summary.reasoning

    async def _persist_state(self, state: OptimizationState) -> None:
        """Persist the mutable fields of ``state`` to the states repository."""

        await self._states.update(
            state.id,
            {
                "current_prompt": state.current_prompt,
                "avg_score": state.avg_score,
                "strengths": state.strengths,
                "weaknesses": state.weaknesses,
                "reasoning": state.reasoning,
            },
        )

    # -- progress -------------------------------------------------------------

    async def _emit(self, run_id: str, event: dict[str, Any]) -> None:
        """Publish a progress event through the tracker (no-op when absent)."""

        if self._progress is None:
            return
        try:
            await self._progress.publish(run_id, event)
        except Exception:  # progress must never break the loop
            logger.exception("Progress publish failed for run %s", run_id)
