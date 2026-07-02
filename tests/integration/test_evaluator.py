"""Integration tests: EvaluatorService against mongomock (Task 15)."""

from __future__ import annotations

import pytest

from app.core.interfaces import mean_aggregator
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
)
from app.models import Prompt, TestCase
from app.services.evaluator import EvaluatorService
from tests.fakes import FailingEvaluationStep, FakeEvaluationStep, FakeExecutor


def make_evaluator(db, steps) -> EvaluatorService:
    return EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=FakeExecutor,
        steps_resolver=lambda: steps,
        aggregator_resolver=lambda: mean_aggregator,
    )


def make_test_cases(n: int) -> list[TestCase]:
    return [TestCase(name=f"tc{i}") for i in range(n)]


async def test_produces_exactly_cases_times_n_reports(db):
    evaluator = make_evaluator(db, [FakeEvaluationStep(scores=(8,))])
    result = await evaluator.run(Prompt(text="p"), make_test_cases(3), 2)

    assert len(result.points) == 6
    assert len(result.report_ids) == 6
    assert await EvaluationReportRepository(db).count_by_run(result.run_id) == 6


async def test_avg_score_is_mean_of_points(db):
    # Two test cases × 1 execution; the shared step yields 4 then 8.
    step = FakeEvaluationStep(scores=(4, 8))
    evaluator = make_evaluator(db, [step])
    result = await evaluator.run(Prompt(text="p"), make_test_cases(2), 1)
    assert result.avg_score == pytest.approx(6.0)


async def test_multiple_steps_aggregate_per_point(db):
    steps = [FakeEvaluationStep("a", scores=(4,)), FakeEvaluationStep("b", scores=(8,))]
    evaluator = make_evaluator(db, steps)
    result = await evaluator.run(Prompt(text="p"), make_test_cases(1), 1)
    assert result.points[0].aggregated_score == pytest.approx(6.0)
    assert len(result.points[0].step_evaluations) == 2


async def test_standalone_run_lifecycle_persisted(db):
    evaluator = make_evaluator(db, [FakeEvaluationStep(scores=(9,))])
    result = await evaluator.run(Prompt(text="p"), make_test_cases(1), 1)

    run_doc = await EvaluationRunRepository(db).get(result.run_id)
    assert run_doc is not None
    assert run_doc["status"] == "completed"
    assert run_doc["avg_score"] == pytest.approx(9.0)


async def test_rejects_empty_test_cases_and_bad_n(db):
    evaluator = make_evaluator(db, [FakeEvaluationStep()])
    with pytest.raises(ValueError):
        await evaluator.run(Prompt(text="p"), [], 1)
    with pytest.raises(ValueError):
        await evaluator.run(Prompt(text="p"), make_test_cases(1), 0)


async def test_failing_step_isolated_as_failed_report(db):
    evaluator = make_evaluator(db, [FailingEvaluationStep()])
    result = await evaluator.run(Prompt(text="p"), make_test_cases(1), 1)

    assert result.points[0].aggregated_score == 1.0
    report = await EvaluationReportRepository(db).get(result.report_ids[0])
    assert any("scripted step failure" in w for w in report["weaknesses"])


async def test_progress_hook_receives_events(db):
    events: list[dict] = []
    evaluator = make_evaluator(db, [FakeEvaluationStep(scores=(7,))])
    await evaluator.run(
        Prompt(text="p"), make_test_cases(2), 1, progress=events.append
    )
    executed = [e for e in events if e["event"] == "executed"]
    assert len(executed) == 2
    assert events[-1]["event"] == "completed"
