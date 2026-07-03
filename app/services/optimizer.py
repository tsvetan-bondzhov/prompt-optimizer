"""Prompt Optimizer service & feedback loop (Task 09).

The :class:`OptimizerService` drives the optimization feedback loop described in
implementation plan §6.2. Given an :class:`Prompt` (the current best
prompt for a goal) and a :class:`RunConfig`, it iteratively asks a
:class:`~app.core.interfaces.PromptOptimizer` for a better prompt, re-evaluates it
with the :class:`~app.services.evaluator.EvaluatorService`, summarizes the
results with the :class:`~app.services.summarizer.SummarizerService`, and accepts
the proposal only when its average score is **strictly greater** than the
current best.

It mirrors :class:`EvaluatorService`'s design: every collaborator (evaluator,
summarizer, optimizer, repositories, progress tracker) is injected so nothing is
hardcoded and tests can swap in fakes. The optimizer is resolved through
:func:`app.core.registry.get_prompt_optimizer` by default.

Key behaviours (plan §6.2 / §9):

* **First-run baseline:** when ``prompt.avg_score`` is ``None`` the evaluator runs
  exactly once on the current prompt to establish a baseline score + summary;
  that baseline is persisted as its own viewable :class:`EvaluationRun`.
* **Strict acceptance:** the persisted prompt advances only when a proposal scores
  strictly higher than the current best.
* **Full persistence:** every iteration persists an :class:`OptimizationStep`
  (proposed prompt + all report links), accepted or not. The evaluator persists
  all pre-summarization reports linked to the owning optimization run.
* **Failure handling:** optimizer/LLM/evaluator failures mark the run ``failed``,
  persist partial results, emit an ``error`` progress event, and re-raise.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional

from app.config import get_settings
from app.core.registry import get_prompt_optimizer
from app.core.interfaces import PromptOptimizer
from app.db.repositories.reports import EvaluationReportRepository
from app.db.repositories.runs import OptimizationRunRepository
from app.db.repositories.prompts import PromptRepository
from app.db.repositories.steps import OptimizationStepRepository
from app.db.repositories.test_cases import TestCaseRepository
from app.models import (
    EvaluationSummary,
    OptimizationContext,
    OptimizationRun,
    Prompt,
    OptimizationStep,
    PromptText,
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

# Resolver callable returning the active optimizer (defaults to the registry
# helper, overridable for tests).
OptimizerResolver = Callable[[], PromptOptimizer]


class OptimizerService:
    """Run the optimization feedback loop for a stored optimization prompt."""

    def __init__(
        self,
        evaluator: EvaluatorService,
        summarizer: SummarizerService,
        prompt_repository: PromptRepository,
        run_repository: OptimizationRunRepository,
        step_repository: OptimizationStepRepository,
        test_case_repository: TestCaseRepository,
        *,
        report_repository: Optional[EvaluationReportRepository] = None,
        optimizer_resolver: OptimizerResolver = get_prompt_optimizer,
        progress: Optional[ProgressTracker] = None,
    ) -> None:
        """:param evaluator: Evaluates a prompt across test cases (Task 08).
        :param summarizer: Condenses evaluation points into a summary (Task 10).
        :param prompt_repository: Loads/persists the best :class:`Prompt`.
        :param run_repository: Creates/updates the :class:`OptimizationRun`.
        :param step_repository: Persists one :class:`OptimizationStep` per iteration.
        :param test_case_repository: Resolves ``prompt.test_case_ids`` to test cases.
        :param report_repository: Optional reports repo (reports are persisted by
            the evaluator; injected for API completeness / future use).
        :param optimizer_resolver: Returns the active :class:`PromptOptimizer`.
        :param progress: Optional :class:`ProgressTracker` for live events.
        """

        self._evaluator = evaluator
        self._summarizer = summarizer
        self._prompts = prompt_repository
        self._runs = run_repository
        self._steps = step_repository
        self._test_cases = test_case_repository
        self._reports = report_repository
        self._optimizer_resolver = optimizer_resolver
        self._progress = progress

    async def optimize(
        self, prompt_id: str, config: RunConfig, run_id: Optional[str] = None
    ) -> Prompt:
        """Run the optimization loop for ``prompt_id`` and return the final prompt.

        Implements the plan §6.2 loop: optional first-run baseline, then improve
        / evaluate / summarize / (strictly) accept until the target score is met
        or the iteration budget is exhausted. Every iteration persists an
        :class:`OptimizationStep`; the best :class:`Prompt` advances
        only on a strictly greater score.

        :param prompt_id: Id of the :class:`Prompt` to optimize.
        :param config: Tunable run parameters (target/iterations/executions).
        :param run_id: Optional id of a pre-created (``pending``)
            :class:`OptimizationRun` — used by API routes that create the run
            document up-front to return the id immediately, then execute the
            loop in the background. When ``None`` a fresh run is created.
        :returns: The final (possibly updated) :class:`Prompt`.
        :raises ValueError: If the prompt is not found or has no test cases.
        :raises Exception: Re-raises optimizer/evaluator failures after marking the
            run failed and persisting partial results.
        """

        prompt = await self._load_prompt(prompt_id)
        test_cases = await self._load_test_cases(prompt)

        if run_id is None:
            run = await self._create_run(prompt_id, config)
            run_id = run.id
        else:
            await self._start_pending_run(run_id, config)
        hook = self._progress.make_hook(run_id) if self._progress else None

        try:
            # --- Baseline edge case (exactly one extra evaluation) -----------
            if prompt.avg_score is None:
                await self._establish_baseline(prompt, test_cases, config, hook)

            # --- Improvement loop --------------------------------------------
            iteration = 0
            while (
                prompt.avg_score is not None
                and prompt.avg_score < config.target_score
                and iteration < config.max_iterations
            ):
                await self._run_iteration(
                    prompt=prompt,
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
                        "avg_score": prompt.avg_score,
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
                "avg_score": prompt.avg_score,
            },
        )
        return prompt

    # -- loading helpers ------------------------------------------------------

    async def _load_prompt(self, prompt_id: str) -> Prompt:
        """Load and validate the :class:`Prompt` for ``prompt_id``."""

        doc = await self._prompts.get(prompt_id)
        if doc is None:
            raise ValueError(f"Prompt {prompt_id!r} not found.")
        return Prompt.model_validate(doc)

    async def _load_test_cases(
        self, prompt: Prompt
    ) -> list[TestCase]:
        """Resolve ``prompt.test_case_ids`` into :class:`TestCase` models."""

        if not prompt.test_case_ids:
            raise ValueError(
                f"Prompt {prompt.id!r} has no test cases to optimize "
                "against."
            )
        docs = await self._test_cases.list_by_ids(prompt.test_case_ids)
        if not docs:
            raise ValueError(
                f"None of the test cases referenced by prompt {prompt.id!r} exist."
            )
        # Preserve the prompt's declared ordering for deterministic evaluation.
        by_id = {doc["id"]: doc for doc in docs}
        ordered = [by_id[tcid] for tcid in prompt.test_case_ids if tcid in by_id]
        return [TestCase.model_validate(doc) for doc in ordered]

    async def _create_run(
        self, prompt_id: str, config: RunConfig
    ) -> OptimizationRun:
        """Create and persist a fresh ``running`` :class:`OptimizationRun`."""

        run = OptimizationRun(
            prompt_id=prompt_id,
            config=config,
            status=RunStatus.RUNNING,
            progress=RunProgress(
                total=config.max_iterations,
                status=RunStatus.RUNNING,
            ),
        )
        await self._runs.create(run.model_dump())
        return run

    async def _start_pending_run(self, run_id: str, config: RunConfig) -> None:
        """Move a pre-created (``pending``) run into ``running`` prompt."""

        await self._runs.update(
            run_id,
            {
                "config": config.model_dump(),
                "progress": RunProgress(
                    total=config.max_iterations,
                    status=RunStatus.RUNNING,
                ).model_dump(mode="json"),
            },
        )
        await self._runs.update_status(run_id, RunStatus.RUNNING.value)

    # -- loop building blocks -------------------------------------------------

    async def _establish_baseline(
        self,
        prompt: Prompt,
        test_cases: list[TestCase],
        config: RunConfig,
        hook: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Run exactly one baseline evaluation and fold it into ``prompt``.

        The baseline evaluation creates its own standalone, viewable
        :class:`EvaluationRun` (``run_id=None``), so it is persisted and visible
        independently of the optimization run.
        """

        baseline = await self._evaluator.run(
            PromptText(text=prompt.current_prompt),
            test_cases,
            config.executions_per_test_case,
            run_id=None,
            progress=hook,
            prompt_name=prompt.name,
        )
        summary = await self._summarizer.summarize(baseline.points)
        self._apply_summary(prompt, baseline.avg_score, summary)
        await self._persist_prompt(prompt)

    async def _run_iteration(
        self,
        *,
        prompt: Prompt,
        test_cases: list[TestCase],
        config: RunConfig,
        run_id: str,
        iteration: int,
        hook: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Run a single improve / evaluate / summarize / accept iteration."""

        previous_prompt = prompt.current_prompt
        previous_avg = prompt.avg_score

        # 1. Propose an improved prompt from the current context.
        ctx = OptimizationContext(
            goal=prompt.goal,
            current_prompt=prompt.current_prompt,
            strengths=prompt.strengths,
            weaknesses=prompt.weaknesses,
            avg_score=prompt.avg_score,
            reasoning=prompt.reasoning,
            system_prompt=get_settings().OPTIMIZER_SYSTEM_PROMPT,
        )
        optimizer = self._optimizer_resolver()
        proposed = await optimizer.optimize(ctx)

        # 2. Evaluate it, linking all reports to the owning optimization run.
        eval_result = await self._evaluator.run(
            proposed,
            test_cases,
            config.executions_per_test_case,
            run_id=run_id,
            progress=hook,
            prompt_name=prompt.name,
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

        # 5. Advance the best prompt only on a strictly better score.
        if accepted:
            self._apply_summary(prompt, new_avg, summary, current_prompt=proposed.text)
            await self._persist_prompt(prompt)

    # -- prompt mutation helpers ----------------------------------------------

    @staticmethod
    def _apply_summary(
        prompt: Prompt,
        avg_score: float,
        summary: EvaluationSummary,
        *,
        current_prompt: Optional[str] = None,
    ) -> None:
        """Fold an evaluation summary + score into ``prompt`` (in place)."""

        if current_prompt is not None:
            prompt.current_prompt = current_prompt
        prompt.avg_score = avg_score
        prompt.strengths = summary.strengths
        prompt.weaknesses = summary.weaknesses
        prompt.reasoning = summary.reasoning

    async def _persist_prompt(self, prompt: Prompt) -> None:
        """Persist the mutable fields of ``prompt`` to the prompts repository."""

        await self._prompts.update(
            prompt.id,
            {
                "current_prompt": prompt.current_prompt,
                "avg_score": prompt.avg_score,
                "strengths": prompt.strengths,
                "weaknesses": prompt.weaknesses,
                "reasoning": prompt.reasoning,
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
