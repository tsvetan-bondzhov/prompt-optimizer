"""Integration tests: stopping running evaluation / optimization runs."""

from __future__ import annotations

import asyncio

from app.api.background import cancel_run, execute_optimization_run
from app.core.registry import register
from app.db.repositories import (
    EvaluationRunRepository,
    OptimizationRunRepository,
    PromptRepository,
    TestCaseRepository,
)
from app.models import (
    EvaluationRun,
    OptimizationRun,
    Prompt,
    RunConfig,
    RunStatus,
    TestCase,
)
from app.services.progress import ProgressEventType, ProgressTracker
from tests.fakes import FakeExecutor


class SlowExecutor(FakeExecutor):
    """Blocks long enough for the test to cancel the run mid-evaluation."""

    async def execute(self, prompt, test_case, entry=None, llm_runner=None):
        await asyncio.sleep(30)
        return await super().execute(prompt, test_case, entry, llm_runner)


async def test_cancel_running_optimization(db):
    register("executor", "default", SlowExecutor)
    tracker = ProgressTracker()

    test_case = TestCase(name="tc", grader_names=["fake"])
    await TestCaseRepository(db).create(test_case.model_dump())
    prompt = Prompt(
        name="p", goal="g", current_prompt="base", test_case_ids=[test_case.id]
    )
    await PromptRepository(db).create(prompt.model_dump())
    run = OptimizationRun(prompt_id=prompt.id, status=RunStatus.PENDING)
    await OptimizationRunRepository(db).create(run.model_dump())

    task = asyncio.create_task(
        execute_optimization_run(db, tracker, run.id, prompt.id, RunConfig())
    )
    await asyncio.sleep(0.05)  # let the run start and block in the executor
    assert cancel_run(run.id) is True
    await asyncio.wait_for(task, timeout=5)  # wrapper absorbs the cancellation

    stored = await OptimizationRunRepository(db).get(run.id)
    assert stored["status"] == "cancelled"
    events = tracker.snapshot(run.id).events
    assert events[-1].type is ProgressEventType.RUN_CANCELLED


async def test_cancel_unknown_run_returns_false(db):
    assert cancel_run("no-such-run") is False


async def test_stop_route_marks_dead_running_run_cancelled(client, db):
    # A run stuck in "running" with no live task (e.g. after a restart).
    run = OptimizationRun(prompt_id="p1", status=RunStatus.RUNNING)
    await OptimizationRunRepository(db).create(run.model_dump())

    r = client.post(f"/runs/{run.id}/stop", follow_redirects=False)
    assert r.status_code == 303

    stored = await OptimizationRunRepository(db).get(run.id)
    assert stored["status"] == "cancelled"


async def test_stop_route_404_for_unknown_run(client):
    assert client.post("/runs/missing/stop").status_code == 404


async def test_stop_completed_evaluation_is_a_noop(client, db):
    run = EvaluationRun(prompt="p", status="completed")
    await EvaluationRunRepository(db).create(run.model_dump())

    r = client.post(f"/runs/{run.id}/stop", follow_redirects=False)
    assert r.status_code == 303
    stored = await EvaluationRunRepository(db).get(run.id)
    assert stored["status"] == "completed"
