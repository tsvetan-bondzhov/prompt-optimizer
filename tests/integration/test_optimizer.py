"""Integration tests: OptimizerService feedback loop against mongomock (Task 15)."""

from __future__ import annotations

import pytest

from app.core.interfaces import mean_aggregator
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
    OptimizationRunRepository,
    PromptRepository,
    PromptVersionRepository,
    OptimizationStepRepository,
    TestCaseRepository,
)
from app.models import Prompt, RunConfig, TestCase
from app.services.evaluator import EvaluatorService
from app.services.optimizer import OptimizerService
from app.services.progress import ProgressEventType, ProgressTracker
from app.services.summarizer import SummarizerService
from tests.fakes import FakeGrader, FakeExecutor, FakeOptimizer, FakeSummarizer


async def make_env(
    db,
    scores,
    *,
    avg_score=None,
    progress=None,
    summarizer_service=None,
    prompt_fields=None,
):
    """Build an optimizer wired to fakes, plus a persisted prompt + test case.

    ``scores`` scripts the single evaluation step: with one test case and
    ``executions_per_test_case=1`` each evaluator invocation (baseline or
    iteration) consumes exactly one score.
    """

    test_case = TestCase(name="tc", grader_names=["fake-step"])
    await TestCaseRepository(db).create(test_case.model_dump())

    prompt = Prompt(
        name="test prompt",
        goal="test goal",
        current_prompt="base prompt",
        test_case_ids=[test_case.id],
        avg_score=avg_score,
        **(prompt_fields or {}),
    )
    await PromptRepository(db).create(prompt.model_dump())

    step = FakeGrader(scores=scores)
    evaluator = EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=lambda name: FakeExecutor(),
        grader_resolver=lambda name: step,
        aggregator_resolver=lambda: mean_aggregator,
    )
    optimizer = OptimizerService(
        evaluator,
        summarizer_service or SummarizerService(summarizer_resolver=FakeSummarizer),
        PromptRepository(db),
        OptimizationRunRepository(db),
        OptimizationStepRepository(db),
        TestCaseRepository(db),
        version_repository=PromptVersionRepository(db),
        optimizer_resolver=FakeOptimizer,
        progress=progress,
    )
    return optimizer, prompt


async def test_first_run_establishes_baseline_once(db):
    # Baseline 5, then improvements score 7 and 9 (accepted; 9 hits target).
    optimizer, prompt = await make_env(db, scores=(5, 7, 9))
    final = await optimizer.optimize(
        prompt.id, RunConfig(target_score=9, max_iterations=10)
    )

    # Exactly one standalone EvaluationRun == the baseline (iterations attach
    # their reports to the optimization run instead).
    runs = await EvaluationRunRepository(db).list()
    assert len(runs) == 1
    assert final.avg_score == pytest.approx(9.0)
    assert final.current_prompt != "base prompt"


async def test_no_baseline_when_score_already_known(db):
    optimizer, prompt = await make_env(db, scores=(9,), avg_score=8.0)
    await optimizer.optimize(prompt.id, RunConfig(target_score=9, max_iterations=5))
    assert await EvaluationRunRepository(db).list() == []


async def test_accept_requires_strictly_greater_score(db):
    # Baseline 8; proposals score 8 (tie) then 8 again — never accepted.
    optimizer, prompt = await make_env(db, scores=(8, 8, 8))
    final = await optimizer.optimize(
        prompt.id, RunConfig(target_score=10, max_iterations=2)
    )

    assert final.current_prompt == "base prompt"
    assert final.avg_score == pytest.approx(8.0)


async def test_persists_step_per_iteration_including_rejected(db):
    # Baseline 8; iteration 1 scores 6 (rejected), iteration 2 scores 9 (accepted).
    optimizer, prompt = await make_env(db, scores=(8, 6, 9))
    await optimizer.optimize(prompt.id, RunConfig(target_score=9, max_iterations=5))

    run = (await OptimizationRunRepository(db).list())[0]
    steps = await OptimizationStepRepository(db).list_by_run(run["id"])
    assert len(steps) == 2
    assert steps[0]["accepted"] is False
    assert steps[0]["previous_avg_score"] == pytest.approx(8.0)
    assert steps[0]["new_avg_score"] == pytest.approx(6.0)
    assert steps[1]["accepted"] is True
    assert steps[1]["new_avg_score"] == pytest.approx(9.0)
    # Report links present on every step (rejected included).
    assert all(s["evaluation_report_ids"] for s in steps)


async def test_stops_at_max_iterations(db):
    # Baseline 5 then constant 6 — target unreachable.
    optimizer, prompt = await make_env(db, scores=(5, 6))
    await optimizer.optimize(prompt.id, RunConfig(target_score=10, max_iterations=3))

    run = (await OptimizationRunRepository(db).list())[0]
    steps = await OptimizationStepRepository(db).list_by_run(run["id"])
    assert len(steps) == 3
    assert run["status"] == "completed"


async def test_stops_immediately_when_target_already_met(db):
    optimizer, prompt = await make_env(db, scores=(9,), avg_score=9.5)
    await optimizer.optimize(prompt.id, RunConfig(target_score=9, max_iterations=5))
    run = (await OptimizationRunRepository(db).list())[0]
    assert await OptimizationStepRepository(db).count_by_run(run["id"]) == 0


async def test_prompt_updated_only_on_acceptance(db):
    # Baseline 8, single rejected iteration (6).
    optimizer, prompt = await make_env(db, scores=(8, 6))
    await optimizer.optimize(prompt.id, RunConfig(target_score=10, max_iterations=1))

    stored = await PromptRepository(db).get(prompt.id)
    assert stored["current_prompt"] == "base prompt"
    assert stored["avg_score"] == pytest.approx(8.0)


async def test_accepted_iteration_snapshots_previous_version(db):
    # Baseline 5; improvements score 7 and 9 — two accepted iterations, each
    # preserving the outgoing prompt text + score as a version.
    optimizer, prompt = await make_env(db, scores=(5, 7, 9))
    await optimizer.optimize(prompt.id, RunConfig(target_score=9, max_iterations=10))

    versions = await PromptVersionRepository(db).list_by_prompt(prompt.id)
    assert [v["version_number"] for v in versions] == [2, 1]
    first, second = versions[1], versions[0]
    assert first["prompt_text"] == "base prompt"
    assert first["avg_score"] == pytest.approx(5.0)
    assert second["avg_score"] == pytest.approx(7.0)
    assert second["prompt_text"] != "base prompt"

    run = (await OptimizationRunRepository(db).list())[0]
    assert all(v["run_id"] == run["id"] for v in versions)
    assert await PromptVersionRepository(db).list_by_run(run["id"]) == list(
        reversed(versions)
    )


async def test_rejected_iterations_save_no_version(db):
    # Baseline 8; proposals score 8 (tie) twice — nothing accepted, no versions.
    optimizer, prompt = await make_env(db, scores=(8, 8, 8))
    await optimizer.optimize(prompt.id, RunConfig(target_score=10, max_iterations=2))
    assert await PromptVersionRepository(db).list_by_prompt(prompt.id) == []


async def test_nested_evaluation_completion_does_not_terminate_run(db):
    # Baseline 5, then 6 / 7 / 8 — three accepted iterations before the target.
    # Each nested evaluation emits a raw "completed" event; none of them may
    # surface as run_completed on the optimization run's progress channel.
    tracker = ProgressTracker()
    optimizer, prompt = await make_env(db, scores=(5, 6, 7, 8), progress=tracker)
    await optimizer.optimize(prompt.id, RunConfig(target_score=8, max_iterations=5))

    run = (await OptimizationRunRepository(db).list())[0]
    events = tracker.snapshot(run["id"]).events
    completed = [e for e in events if e.type is ProgressEventType.RUN_COMPLETED]
    assert len(completed) == 1
    assert events[-1].type is ProgressEventType.RUN_COMPLETED
    iterations = [e for e in events if e.type is ProgressEventType.ITERATION_DONE]
    assert len(iterations) == 3
    # The iterations card consumes these fields from the serialized frame.
    assert [e.executed for e in iterations] == [1, 2, 3]
    assert all(e.total == 5 for e in iterations)
    # Each event carries the freshly accepted score (the prompt is mutated in
    # place before the emit), never a stale pre-iteration value.
    assert [getattr(e, "avg_score", None) for e in iterations] == [6.0, 7.0, 8.0]
    assert '"avg_score":' in iterations[-1].model_dump_json()


async def test_summarizer_uses_prompt_runner_selection(db):
    from app.models import EvaluationSummary

    captured: list[tuple] = []

    class SpySummarizerService:
        async def summarize(
            self, points, llm_runner_name=None, llm_runner_options=None
        ):
            captured.append((llm_runner_name, llm_runner_options))
            return EvaluationSummary(reasoning="spy")

    # Baseline (5) + one accepted iteration (9) — two summarize calls, both
    # with the runner selected on the prompt.
    optimizer, prompt = await make_env(
        db,
        scores=(5, 9),
        summarizer_service=SpySummarizerService(),
        prompt_fields={
            "summarizer_llm_runner": "ollama",
            "summarizer_llm_runner_options": {"model": "mistral"},
        },
    )
    await optimizer.optimize(prompt.id, RunConfig(target_score=9, max_iterations=3))

    assert len(captured) == 2
    assert all(c == ("ollama", {"model": "mistral"}) for c in captured)


async def test_missing_prompt_raises(db):
    optimizer, _ = await make_env(db, scores=(8,))
    with pytest.raises(ValueError):
        await optimizer.optimize("no-such-prompt", RunConfig())
