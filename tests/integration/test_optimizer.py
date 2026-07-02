"""Integration tests: OptimizerService feedback loop against mongomock (Task 15)."""

from __future__ import annotations

import pytest

from app.core.interfaces import mean_aggregator
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
    OptimizationRunRepository,
    OptimizationStateRepository,
    OptimizationStepRepository,
    TestCaseRepository,
)
from app.models import OptimizationState, RunConfig, TestCase
from app.services.evaluator import EvaluatorService
from app.services.optimizer import OptimizerService
from app.services.summarizer import SummarizerService
from tests.fakes import FakeEvaluationStep, FakeExecutor, FakeImprover, FakeSummarizer


async def make_env(db, scores, *, avg_score=None):
    """Build an optimizer wired to fakes, plus a persisted state + test case.

    ``scores`` scripts the single evaluation step: with one test case and
    ``executions_per_test_case=1`` each evaluator invocation (baseline or
    iteration) consumes exactly one score.
    """

    test_case = TestCase(name="tc")
    await TestCaseRepository(db).create(test_case.model_dump())

    state = OptimizationState(
        goal="test goal",
        current_prompt="base prompt",
        test_case_ids=[test_case.id],
        avg_score=avg_score,
    )
    await OptimizationStateRepository(db).create(state.model_dump())

    step = FakeEvaluationStep(scores=scores)
    evaluator = EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=FakeExecutor,
        steps_resolver=lambda: [step],
        aggregator_resolver=lambda: mean_aggregator,
    )
    optimizer = OptimizerService(
        evaluator,
        SummarizerService(summarizer_resolver=FakeSummarizer),
        OptimizationStateRepository(db),
        OptimizationRunRepository(db),
        OptimizationStepRepository(db),
        TestCaseRepository(db),
        improver_resolver=FakeImprover,
    )
    return optimizer, state


async def test_first_run_establishes_baseline_once(db):
    # Baseline 5, then improvements score 7 and 9 (accepted; 9 hits target).
    optimizer, state = await make_env(db, scores=(5, 7, 9))
    final = await optimizer.optimize(
        state.id, RunConfig(target_score=9, max_iterations=10)
    )

    # Exactly one standalone EvaluationRun == the baseline (iterations attach
    # their reports to the optimization run instead).
    runs = await EvaluationRunRepository(db).list()
    assert len(runs) == 1
    assert final.avg_score == pytest.approx(9.0)
    assert final.current_prompt != "base prompt"


async def test_no_baseline_when_score_already_known(db):
    optimizer, state = await make_env(db, scores=(9,), avg_score=8.0)
    await optimizer.optimize(state.id, RunConfig(target_score=9, max_iterations=5))
    assert await EvaluationRunRepository(db).list() == []


async def test_accept_requires_strictly_greater_score(db):
    # Baseline 8; proposals score 8 (tie) then 8 again — never accepted.
    optimizer, state = await make_env(db, scores=(8, 8, 8))
    final = await optimizer.optimize(
        state.id, RunConfig(target_score=10, max_iterations=2)
    )

    assert final.current_prompt == "base prompt"
    assert final.avg_score == pytest.approx(8.0)


async def test_persists_step_per_iteration_including_rejected(db):
    # Baseline 8; iteration 1 scores 6 (rejected), iteration 2 scores 9 (accepted).
    optimizer, state = await make_env(db, scores=(8, 6, 9))
    await optimizer.optimize(state.id, RunConfig(target_score=9, max_iterations=5))

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
    optimizer, state = await make_env(db, scores=(5, 6))
    await optimizer.optimize(state.id, RunConfig(target_score=10, max_iterations=3))

    run = (await OptimizationRunRepository(db).list())[0]
    steps = await OptimizationStepRepository(db).list_by_run(run["id"])
    assert len(steps) == 3
    assert run["status"] == "completed"


async def test_stops_immediately_when_target_already_met(db):
    optimizer, state = await make_env(db, scores=(9,), avg_score=9.5)
    await optimizer.optimize(state.id, RunConfig(target_score=9, max_iterations=5))
    run = (await OptimizationRunRepository(db).list())[0]
    assert await OptimizationStepRepository(db).count_by_run(run["id"]) == 0


async def test_state_updated_only_on_acceptance(db):
    # Baseline 8, single rejected iteration (6).
    optimizer, state = await make_env(db, scores=(8, 6))
    await optimizer.optimize(state.id, RunConfig(target_score=10, max_iterations=1))

    stored = await OptimizationStateRepository(db).get(state.id)
    assert stored["current_prompt"] == "base prompt"
    assert stored["avg_score"] == pytest.approx(8.0)


async def test_missing_state_raises(db):
    optimizer, _ = await make_env(db, scores=(8,))
    with pytest.raises(ValueError):
        await optimizer.optimize("no-such-state", RunConfig())
