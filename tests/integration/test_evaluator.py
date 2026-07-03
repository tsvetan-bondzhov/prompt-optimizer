"""Integration tests: EvaluatorService against mongomock (Task 15)."""

from __future__ import annotations

import pytest

from app.core.interfaces import mean_aggregator
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
)
from app.models import PromptText, TestCase
from app.services.evaluator import EvaluatorService
from tests.fakes import FailingGrader, FakeGrader, FakeExecutor


def make_evaluator(db, graders) -> EvaluatorService:
    by_name = {g.name: g for g in graders}
    return EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=lambda name: FakeExecutor(),
        grader_resolver=lambda name: by_name[name],
        aggregator_resolver=lambda: mean_aggregator,
    )


def make_test_cases(
    n: int, grader_names: list[str] = ("fake-step",)
) -> list[TestCase]:
    return [
        TestCase(name=f"tc{i}", grader_names=list(grader_names))
        for i in range(n)
    ]


async def test_produces_exactly_cases_times_n_reports(db):
    evaluator = make_evaluator(db, [FakeGrader(scores=(8,))])
    result = await evaluator.run(PromptText(text="p"), make_test_cases(3), 2)

    assert len(result.points) == 6
    assert len(result.report_ids) == 6
    assert await EvaluationReportRepository(db).count_by_run(result.run_id) == 6


async def test_avg_score_is_mean_of_points(db):
    # Two test cases × 1 execution; the shared step yields 4 then 8.
    step = FakeGrader(scores=(4, 8))
    evaluator = make_evaluator(db, [step])
    result = await evaluator.run(PromptText(text="p"), make_test_cases(2), 1)
    assert result.avg_score == pytest.approx(6.0)


async def test_multiple_steps_aggregate_per_point(db):
    steps = [FakeGrader("a", scores=(4,)), FakeGrader("b", scores=(8,))]
    evaluator = make_evaluator(db, steps)
    result = await evaluator.run(
        PromptText(text="p"), make_test_cases(1, ["a", "b"]), 1
    )
    assert result.points[0].aggregated_score == pytest.approx(6.0)
    assert len(result.points[0].grader_evaluations) == 2


async def test_standalone_run_lifecycle_persisted(db):
    evaluator = make_evaluator(db, [FakeGrader(scores=(9,))])
    result = await evaluator.run(PromptText(text="p"), make_test_cases(1), 1)

    run_doc = await EvaluationRunRepository(db).get(result.run_id)
    assert run_doc is not None
    assert run_doc["status"] == "completed"
    assert run_doc["avg_score"] == pytest.approx(9.0)


async def test_rejects_empty_test_cases_and_bad_n(db):
    evaluator = make_evaluator(db, [FakeGrader()])
    with pytest.raises(ValueError):
        await evaluator.run(PromptText(text="p"), [], 1)
    with pytest.raises(ValueError):
        await evaluator.run(PromptText(text="p"), make_test_cases(1), 0)


async def test_failing_step_isolated_as_failed_report(db):
    evaluator = make_evaluator(db, [FailingGrader()])
    result = await evaluator.run(
        PromptText(text="p"), make_test_cases(1, ["failing-step"]), 1
    )

    assert result.points[0].aggregated_score == 1.0
    report = await EvaluationReportRepository(db).get(result.report_ids[0])
    assert any("scripted step failure" in w for w in report["weaknesses"])


async def test_progress_hook_receives_events(db):
    events: list[dict] = []
    evaluator = make_evaluator(db, [FakeGrader(scores=(7,))])
    await evaluator.run(
        PromptText(text="p"), make_test_cases(2), 1, progress=events.append
    )
    executed = [e for e in events if e["event"] == "executed"]
    assert len(executed) == 2
    assert events[-1]["event"] == "completed"


async def test_each_data_entry_executed_and_scored_individually(db):
    # One test case with 3 data entries: the shared grader yields 4, 8, 9.
    step = FakeGrader(scores=(4, 8, 9))
    evaluator = make_evaluator(db, [step])
    test_case = TestCase(
        name="tc",
        data=[{"a": 1}, {"a": 2}, {"a": 3}],
        grader_names=["fake-step"],
    )

    result = await evaluator.run(PromptText(text="p"), [test_case], 1)

    point = result.points[0]
    assert len(point.entry_results) == 3
    assert [er.score for er in point.entry_results] == [4.0, 8.0, 9.0]
    assert point.aggregated_score == pytest.approx(7.0)  # mean over entries
    assert step.calls == 3


async def test_failing_entry_is_isolated(db):
    # First entry fails, second scores 9 -> point = mean(1, 9) = 5.
    class FailFirstExecutor(FakeExecutor):
        async def execute(self, prompt, test_case, entry=None, llm_runner=None):
            if entry and entry.get("boom"):
                raise RuntimeError("scripted entry failure")
            return await super().execute(prompt, test_case, entry, llm_runner)

    evaluator = EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=lambda name: FailFirstExecutor(),
        grader_resolver=lambda name: FakeGrader(scores=(9,)),
        aggregator_resolver=lambda: mean_aggregator,
    )
    test_case = TestCase(
        name="tc",
        data=[{"boom": True}, {"ok": True}],
        grader_names=["fake-step"],
    )
    result = await evaluator.run(PromptText(text="p"), [test_case], 1)

    point = result.points[0]
    assert point.aggregated_score == pytest.approx(5.0)
    report = await EvaluationReportRepository(db).get(result.report_ids[0])
    assert any("scripted entry failure" in w for w in report["weaknesses"])


async def test_test_case_without_graders_rejected(db):
    evaluator = make_evaluator(db, [FakeGrader()])
    with pytest.raises(ValueError, match="no graders selected"):
        await evaluator.run(
            PromptText(text="p"), make_test_cases(1, grader_names=[]), 1
        )


async def test_executor_and_runner_resolved_per_test_case(db):
    resolved: dict[str, list[str]] = {"executors": [], "runners": []}

    def executor_resolver(name):
        resolved["executors"].append(name)
        return FakeExecutor()

    def runner_resolver(name):
        resolved["runners"].append(name)
        return object()  # FakeExecutor ignores the runner

    grader = FakeGrader(scores=(8,))
    evaluator = EvaluatorService(
        EvaluationReportRepository(db),
        EvaluationRunRepository(db),
        executor_resolver=executor_resolver,
        grader_resolver=lambda name: grader,
        llm_runner_resolver=runner_resolver,
        aggregator_resolver=lambda: mean_aggregator,
    )
    test_case = TestCase(
        name="tc",
        grader_names=["fake-step"],
        executor_name="template",
        executor_llm_runner="ollama",
    )
    await evaluator.run(PromptText(text="p"), [test_case], 1)

    assert resolved["executors"] == ["template"]
    assert resolved["runners"] == ["ollama"]
