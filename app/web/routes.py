"""Server-rendered web UI routes (Task 14).

Jinja2 pages for managing test cases and prompts, launching evaluation /
optimization runs, watching live progress (SSE), and browsing reports. The
routes reuse the same repositories/services and background executors as the
JSON API — no business logic lives here.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.background import (
    cancel_run,
    execute_evaluation_run,
    execute_optimization_run,
)
from app.api.deps import (
    get_evaluation_run_repository,
    get_optimization_run_repository,
    get_report_repository,
    get_prompt_repository,
    get_prompt_version_repository,
    get_step_repository,
    get_test_case_repository,
)
from app.api.routes_evaluation import resolve_test_cases
from app.core.registry import available, describe
from app.db.repositories import (
    EvaluationReportRepository,
    EvaluationRunRepository,
    OptimizationRunRepository,
    PromptRepository,
    PromptVersionRepository,
    OptimizationStepRepository,
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

router = APIRouter(include_in_schema=False)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["tojson_pretty"] = lambda value: json.dumps(
    value, indent=2, default=str
)
# Cache-busting version for /static assets: browsers heuristically cache JS/CSS
# without revalidating, so stale scripts survive deploys unless the URL changes.
templates.env.globals["static_v"] = str(
    int(max(p.stat().st_mtime for p in STATIC_DIR.glob("*")))
)


def _render(request: Request, name: str, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context)


def _parse_json_field(raw: str, field: str) -> dict[str, Any]:
    """Parse a JSON object form field, raising a readable 400 on bad input."""

    raw = (raw or "").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Field {field!r} is not valid JSON: {exc}.",
        ) from None
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Field {field!r} must be a JSON object.",
        )
    return value


def _runner_selection_fields(form: Any) -> dict[str, Any]:
    """Executor / LLM-runner selections + options from a test case form."""

    fields: dict[str, Any] = {}
    for key in ("executor_name", "executor_llm_runner"):
        value = str(form.get(key, "")).strip()
        if value:
            fields[key] = value
    fields["executor_llm_runner_options"] = _runner_options(
        form, "executor_llm_runner"
    )
    return fields


def _runner_options(form: Any, prefix: str) -> dict[str, Any]:
    """Collect ``<prefix>_opt_*`` runner option inputs (empty values ignored)."""

    options: dict[str, Any] = {}
    for key in ("model", "effort", "temperature"):
        value = str(form.get(f"{prefix}_opt_{key}", "")).strip()
        if not value:
            continue
        if key == "temperature":
            try:
                options[key] = float(value)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Field {prefix}_opt_temperature must be a number.",
                ) from None
        else:
            options[key] = value
    return options


def _llm_runner_options_map() -> dict[str, Any]:
    """Runner name -> options schema, for the runner-options UI."""

    return {info["name"]: info["options_schema"] for info in describe("llm_runner")}


def _parse_json_array_field(raw: str, field: str) -> list[dict[str, Any]]:
    """Parse a JSON array-of-objects form field (a single object is wrapped)."""

    raw = (raw or "").strip() or "[]"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Field {field!r} is not valid JSON: {exc}.",
        ) from None
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(
        not isinstance(item, dict) for item in value
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Field {field!r} must be a JSON array of objects.",
        )
    return value


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    prompts: PromptRepository = Depends(get_prompt_repository),
    opt_runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    eval_runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> HTMLResponse:
    prompt_docs = await prompts.list(limit=50)
    prompt_names = {s["id"]: s.get("name") or s["goal"] for s in prompt_docs}
    return _render(
        request,
        "dashboard.html",
        prompts=prompt_docs,
        prompt_names=prompt_names,
        optimization_runs=await opt_runs.list(limit=10),
        evaluation_runs=await eval_runs.list(limit=10),
    )


# --------------------------------------------------------------------------
# Test cases
# --------------------------------------------------------------------------


@router.get("/test-cases", response_class=HTMLResponse)
async def test_cases_page(
    request: Request,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    return _render(request, "test_cases.html", test_cases=await repo.list(limit=500))


@router.get("/test-cases/new", response_class=HTMLResponse)
async def test_case_new(request: Request) -> HTMLResponse:
    return _render(
        request,
        "test_case_form.html",
        test_case=None,
        grader_infos=describe("grader"),
        executor_infos=describe("executor"),
        available_llm_runners=available("llm_runner"),
        llm_runner_options_map=_llm_runner_options_map(),
    )


@router.post("/test-cases")
async def test_case_create(
    request: Request,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> RedirectResponse:
    form = await request.form()
    test_case = TestCase(
        name=str(form.get("name", "")).strip(),
        data=_parse_json_array_field(str(form.get("data", "")), "data"),
        evaluation_criteria_per_entry=_parse_json_array_field(
            str(form.get("evaluation_criteria_per_entry", "")),
            "evaluation_criteria_per_entry",
        ),
        evaluation_criteria=_parse_json_field(
            str(form.get("evaluation_criteria", "")), "evaluation_criteria"
        ),
        grader_names=[str(v) for v in form.getlist("grader_names")],
        **_runner_selection_fields(form),
    )
    await repo.create(test_case.model_dump())
    return RedirectResponse("/test-cases", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/test-cases/import")
async def test_case_import(
    request: Request,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> RedirectResponse:
    form = await request.form()
    raw = str(form.get("payload", "")).strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"Import payload is not valid JSON: {exc}."
        ) from None
    if not isinstance(items, list) or not items:
        raise HTTPException(
            status_code=400,
            detail="Import payload must be a non-empty JSON array of test cases.",
        )
    for item in items:
        test_case = TestCase(
            name=str(item.get("name", "")).strip(),
            data=item.get("data") or [],
            evaluation_criteria_per_entry=(
                item.get("evaluation_criteria_per_entry") or []
            ),
            evaluation_criteria=item.get("evaluation_criteria") or {},
            grader_names=item.get("grader_names") or [],
            executor_llm_runner_options=(
                item.get("executor_llm_runner_options") or {}
            ),
        )
        await repo.create(test_case.model_dump())
    return RedirectResponse("/test-cases", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/test-cases/{test_case_id}/edit", response_class=HTMLResponse)
async def test_case_edit(
    request: Request,
    test_case_id: str,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    doc = await repo.get(test_case_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Test case not found.")
    return _render(
        request,
        "test_case_form.html",
        test_case=doc,
        grader_infos=describe("grader"),
        executor_infos=describe("executor"),
        available_llm_runners=available("llm_runner"),
        llm_runner_options_map=_llm_runner_options_map(),
    )


@router.post("/test-cases/{test_case_id}")
async def test_case_update(
    request: Request,
    test_case_id: str,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> RedirectResponse:
    form = await request.form()
    await repo.update(
        test_case_id,
        {
            "name": str(form.get("name", "")).strip(),
            "data": _parse_json_array_field(str(form.get("data", "")), "data"),
            "evaluation_criteria_per_entry": _parse_json_array_field(
                str(form.get("evaluation_criteria_per_entry", "")),
                "evaluation_criteria_per_entry",
            ),
            "evaluation_criteria": _parse_json_field(
                str(form.get("evaluation_criteria", "")), "evaluation_criteria"
            ),
            "grader_names": [str(v) for v in form.getlist("grader_names")],
            **_runner_selection_fields(form),
        },
    )
    return RedirectResponse("/test-cases", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/test-cases/{test_case_id}/delete")
async def test_case_delete(
    test_case_id: str,
    repo: TestCaseRepository = Depends(get_test_case_repository),
) -> RedirectResponse:
    await repo.delete(test_case_id)
    return RedirectResponse("/test-cases", status_code=status.HTTP_303_SEE_OTHER)


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(
    request: Request,
    repo: PromptRepository = Depends(get_prompt_repository),
) -> HTMLResponse:
    return _render(request, "prompts.html", prompts=await repo.list(limit=500))


@router.get("/prompts/new", response_class=HTMLResponse)
async def prompt_new(
    request: Request,
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    return _render(
        request,
        "prompt_form.html",
        prompt=None,
        test_cases=await test_cases.list(limit=500),
        available_llm_runners=available("llm_runner"),
        llm_runner_options_map=_llm_runner_options_map(),
    )


@router.post("/prompts")
async def prompt_create(
    request: Request,
    repo: PromptRepository = Depends(get_prompt_repository),
) -> RedirectResponse:
    form = await request.form()
    optimizer_runner = str(form.get("optimizer_llm_runner", "")).strip()
    summarizer_runner = str(form.get("summarizer_llm_runner", "")).strip()
    prompt = Prompt(
        name=str(form.get("name", "")).strip(),
        goal=str(form.get("goal", "")).strip(),
        current_prompt=str(form.get("current_prompt", "")),
        test_case_ids=[str(v) for v in form.getlist("test_case_ids")],
        optimizer_llm_runner_options=_runner_options(form, "optimizer_llm_runner"),
        summarizer_llm_runner_options=_runner_options(
            form, "summarizer_llm_runner"
        ),
        **({"optimizer_llm_runner": optimizer_runner} if optimizer_runner else {}),
        **(
            {"summarizer_llm_runner": summarizer_runner}
            if summarizer_runner
            else {}
        ),
    )
    await repo.create(prompt.model_dump())
    return RedirectResponse(
        f"/prompts/{prompt.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/prompts/{prompt_id}", response_class=HTMLResponse)
async def prompt_page(
    request: Request,
    prompt_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
    opt_runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    versions: PromptVersionRepository = Depends(get_prompt_version_repository),
) -> HTMLResponse:
    prompt = await repo.get(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    linked = await test_cases.list_by_ids(prompt.get("test_case_ids") or [])
    return _render(
        request,
        "prompt_detail.html",
        prompt=prompt,
        linked_test_cases=linked,
        runs=await opt_runs.list_by_prompt(prompt_id, limit=20),
        versions=await versions.list_by_prompt(prompt_id, limit=100),
    )


@router.get("/prompts/{prompt_id}/edit", response_class=HTMLResponse)
async def prompt_edit(
    request: Request,
    prompt_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    prompt = await repo.get(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    return _render(
        request,
        "prompt_form.html",
        prompt=prompt,
        test_cases=await test_cases.list(limit=500),
        available_llm_runners=available("llm_runner"),
        llm_runner_options_map=_llm_runner_options_map(),
    )


@router.post("/prompts/{prompt_id}")
async def prompt_update(
    request: Request,
    prompt_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
) -> RedirectResponse:
    existing = await repo.get(prompt_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    form = await request.form()
    changes: dict[str, Any] = {
        "name": str(form.get("name", "")).strip(),
        "goal": str(form.get("goal", "")).strip(),
        "current_prompt": str(form.get("current_prompt", "")),
        "test_case_ids": [str(v) for v in form.getlist("test_case_ids")],
    }
    optimizer_runner = str(form.get("optimizer_llm_runner", "")).strip()
    if optimizer_runner:
        changes["optimizer_llm_runner"] = optimizer_runner
    changes["optimizer_llm_runner_options"] = _runner_options(
        form, "optimizer_llm_runner"
    )
    summarizer_runner = str(form.get("summarizer_llm_runner", "")).strip()
    if summarizer_runner:
        changes["summarizer_llm_runner"] = summarizer_runner
    changes["summarizer_llm_runner_options"] = _runner_options(
        form, "summarizer_llm_runner"
    )
    # A manually edited prompt invalidates the measured score/summary.
    if changes["current_prompt"] != existing.get("current_prompt"):
        changes.update(
            {"avg_score": None, "strengths": [], "weaknesses": [], "reasoning": ""}
        )
    await repo.update(prompt_id, changes)
    return RedirectResponse(
        f"/prompts/{prompt_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/prompts/{prompt_id}/delete")
async def prompt_delete(
    prompt_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
    versions: PromptVersionRepository = Depends(get_prompt_version_repository),
) -> RedirectResponse:
    await repo.delete(prompt_id)
    await versions.delete_by_prompt(prompt_id)
    return RedirectResponse("/prompts", status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/prompts/{prompt_id}/versions/{version_id}", response_class=HTMLResponse
)
async def prompt_version_page(
    request: Request,
    prompt_id: str,
    version_id: str,
    repo: PromptRepository = Depends(get_prompt_repository),
    versions: PromptVersionRepository = Depends(get_prompt_version_repository),
) -> HTMLResponse:
    version = await versions.get(version_id)
    if version is None or version.get("prompt_id") != prompt_id:
        raise HTTPException(status_code=404, detail="Prompt version not found.")
    prompt = await repo.get(prompt_id)
    return _render(
        request,
        "prompt_version_detail.html",
        version=version,
        prompt=prompt,
    )


# --------------------------------------------------------------------------
# Run evaluation / optimization
# --------------------------------------------------------------------------


@router.get("/evaluate", response_class=HTMLResponse)
async def run_evaluation_form(
    request: Request,
    prompt_id: Optional[str] = None,
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
    prompts: PromptRepository = Depends(get_prompt_repository),
) -> HTMLResponse:
    return _render(
        request,
        "run_evaluation.html",
        test_cases=await test_cases.list(limit=500),
        prompts=await prompts.list(limit=100),
        selected_prompt_id=prompt_id,
    )


@router.post("/evaluate")
async def run_evaluation_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    test_case_repo: TestCaseRepository = Depends(get_test_case_repository),
    prompts: PromptRepository = Depends(get_prompt_repository),
) -> RedirectResponse:
    form = await request.form()
    prompt_text = str(form.get("prompt", "")).strip()
    prompt_id = str(form.get("prompt_id", "")).strip()
    prompt_name: Optional[str] = None
    test_case_ids = [str(v) for v in form.getlist("test_case_ids")]
    n = max(1, int(form.get("executions_per_test_case", 1) or 1))
    update_prompt = bool(form.get("update_prompt")) and bool(prompt_id)

    if prompt_id:
        prompt = await prompts.get(prompt_id)
        if prompt is None:
            raise HTTPException(status_code=400, detail="Prompt not found.")
        prompt_name = prompt.get("name")
        if not prompt_text:
            prompt_text = prompt.get("current_prompt") or ""
        if not test_case_ids:
            test_case_ids = list(prompt.get("test_case_ids") or [])

    if not prompt_text:
        raise HTTPException(
            status_code=400, detail="Provide a prompt or select a prompt."
        )
    selected = await resolve_test_cases(test_case_ids, test_case_repo)

    run = EvaluationRun(
        prompt=prompt_text,
        prompt_name=prompt_name,
        test_case_ids=[tc.id for tc in selected],
        executions_per_test_case=n,
        status=RunStatus.PENDING.value,
    )
    await runs.create(run.model_dump())
    background_tasks.add_task(
        execute_evaluation_run,
        request.app.state.db,
        request.app.state.progress_tracker,
        run.id,
        prompt_text,
        selected,
        n,
        prompt_name,
        prompt_id or None,
        update_prompt,
    )
    return RedirectResponse(
        f"/runs/{run.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/evaluations/{run_id}/repeat")
async def run_evaluation_repeat(
    request: Request,
    run_id: str,
    background_tasks: BackgroundTasks,
    runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    test_case_repo: TestCaseRepository = Depends(get_test_case_repository),
) -> RedirectResponse:
    """Re-run a finished evaluation with the same prompt / test cases / N."""

    previous = await runs.get(run_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    selected = await resolve_test_cases(
        list(previous.get("test_case_ids") or []), test_case_repo
    )
    n = int(previous.get("executions_per_test_case") or 1)

    run = EvaluationRun(
        prompt=previous.get("prompt") or "",
        prompt_name=previous.get("prompt_name"),
        test_case_ids=[tc.id for tc in selected],
        executions_per_test_case=n,
        status=RunStatus.PENDING.value,
    )
    await runs.create(run.model_dump())
    background_tasks.add_task(
        execute_evaluation_run,
        request.app.state.db,
        request.app.state.progress_tracker,
        run.id,
        run.prompt,
        selected,
        n,
        run.prompt_name,
    )
    return RedirectResponse(
        f"/runs/{run.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/optimize", response_class=HTMLResponse)
async def run_optimization_form(
    request: Request,
    prompt_id: Optional[str] = None,
    prompts: PromptRepository = Depends(get_prompt_repository),
) -> HTMLResponse:
    return _render(
        request,
        "run_optimization.html",
        prompts=await prompts.list(limit=100),
        selected_prompt_id=prompt_id,
        defaults=RunConfig(),
    )


@router.post("/optimize")
async def run_optimization_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    prompts: PromptRepository = Depends(get_prompt_repository),
) -> RedirectResponse:
    form = await request.form()
    prompt_id = str(form.get("prompt_id", "")).strip()
    prompt = await prompts.get(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=400, detail="Prompt not found.")
    if not prompt.get("test_case_ids"):
        raise HTTPException(
            status_code=400,
            detail="The selected prompt has no linked test cases.",
        )
    config = RunConfig(
        target_score=float(form.get("target_score") or RunConfig().target_score),
        max_iterations=int(form.get("max_iterations") or RunConfig().max_iterations),
        executions_per_test_case=int(
            form.get("executions_per_test_case")
            or RunConfig().executions_per_test_case
        ),
    )

    run = OptimizationRun(
        prompt_id=prompt_id, config=config, status=RunStatus.PENDING
    )
    await runs.create(run.model_dump())
    background_tasks.add_task(
        execute_optimization_run,
        request.app.state.db,
        request.app.state.progress_tracker,
        run.id,
        prompt_id,
        config,
    )
    return RedirectResponse(
        f"/runs/{run.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --------------------------------------------------------------------------
# Progress page
# --------------------------------------------------------------------------


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_progress_page(
    request: Request,
    run_id: str,
    opt_runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    eval_runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> HTMLResponse:
    run = await opt_runs.get(run_id)
    kind = "optimization"
    if run is None:
        run = await eval_runs.get(run_id)
        kind = "evaluation"
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _render(request, "progress.html", run=run, run_id=run_id, kind=kind)


@router.post("/runs/{run_id}/stop")
async def run_stop(
    request: Request,
    run_id: str,
    opt_runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    eval_runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> RedirectResponse:
    """Stop a running evaluation / optimization run."""

    run = await opt_runs.get(run_id)
    repo: Any = opt_runs
    if run is None:
        run = await eval_runs.get(run_id)
        repo = eval_runs
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    # A live task cleans up (status + terminal event) in its wrapper; without
    # one (finished, or the process restarted mid-run) fix the record here.
    if not cancel_run(run_id) and run.get("status") in (
        RunStatus.PENDING.value,
        RunStatus.RUNNING.value,
    ):
        await repo.update(
            run_id,
            {"status": RunStatus.CANCELLED.value, "error": "Stopped by user."},
        )
        await request.app.state.progress_tracker.publish(
            run_id, {"event": "run_cancelled", "current_step": "cancelled"}
        )
    return RedirectResponse(f"/runs/{run_id}", status_code=status.HTTP_303_SEE_OTHER)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------


async def _test_case_names(
    ids: list[str], repo: TestCaseRepository
) -> dict[str, str]:
    docs = await repo.list_by_ids(ids)
    return {d["id"]: d["name"] for d in docs}


@router.get("/evaluations/{run_id}/reports", response_class=HTMLResponse)
async def evaluation_reports_page(
    request: Request,
    run_id: str,
    eval_runs: EvaluationRunRepository = Depends(get_evaluation_run_repository),
    reports: EvaluationReportRepository = Depends(get_report_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    run = await eval_runs.get(run_id)
    report_docs = await reports.list_by_run(run_id)
    if run is None and not report_docs:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    names = await _test_case_names(
        list({r["test_case_id"] for r in report_docs}), test_cases
    )
    return _render(
        request,
        "evaluation_reports.html",
        run=run,
        run_id=run_id,
        reports=report_docs,
        test_case_names=names,
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def evaluation_report_detail_page(
    request: Request,
    report_id: str,
    reports: EvaluationReportRepository = Depends(get_report_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    report = await reports.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    test_case = await test_cases.get(report["test_case_id"])
    return _render(
        request,
        "evaluation_report_detail.html",
        report=report,
        test_case=test_case,
    )


@router.get("/optimizations/{run_id}/iterations", response_class=HTMLResponse)
async def optimization_iterations_page(
    request: Request,
    run_id: str,
    opt_runs: OptimizationRunRepository = Depends(get_optimization_run_repository),
    steps: OptimizationStepRepository = Depends(get_step_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
    versions: PromptVersionRepository = Depends(get_prompt_version_repository),
) -> HTMLResponse:
    run = await opt_runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Optimization run not found.")
    step_docs = await steps.list_by_run(run_id)
    all_tc_ids = {tcid for s in step_docs for tcid in s.get("test_case_ids", [])}
    names = await _test_case_names(list(all_tc_ids), test_cases)
    return _render(
        request,
        "optimization_iterations.html",
        run=run,
        run_id=run_id,
        steps=step_docs,
        test_case_names=names,
        versions=await versions.list_by_run(run_id),
    )


@router.get("/optimizations/{run_id}/steps", include_in_schema=False)
async def optimization_steps_redirect(run_id: str) -> RedirectResponse:
    """Legacy URL — the page moved when 'steps' became 'iterations'."""

    return RedirectResponse(
        f"/optimizations/{run_id}/iterations",
        status_code=status.HTTP_301_MOVED_PERMANENTLY,
    )


@router.get("/iterations/{step_id}", response_class=HTMLResponse)
async def optimization_iteration_detail_page(
    request: Request,
    step_id: str,
    steps: OptimizationStepRepository = Depends(get_step_repository),
    test_cases: TestCaseRepository = Depends(get_test_case_repository),
) -> HTMLResponse:
    step = await steps.get(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found.")
    names = await _test_case_names(step.get("test_case_ids", []), test_cases)
    diff_lines = _diff_lines(step)
    return _render(
        request,
        "optimization_iteration_detail.html",
        step=step,
        test_case_names=names,
        diff_lines=diff_lines,
    )


@router.get("/steps/{step_id}", include_in_schema=False)
async def optimization_step_detail_redirect(step_id: str) -> RedirectResponse:
    """Legacy URL — the page moved when 'steps' became 'iterations'."""

    return RedirectResponse(
        f"/iterations/{step_id}", status_code=status.HTTP_301_MOVED_PERMANENTLY
    )


def _diff_lines(step: dict[str, Any]) -> list[str]:
    """Unified diff between an iteration's previous and proposed prompt."""

    return list(
        difflib.unified_diff(
            (step.get("previous_prompt") or "").splitlines(),
            (step.get("proposed_prompt") or "").splitlines(),
            fromfile="previous prompt",
            tofile="proposed prompt",
            lineterm="",
        )
    )
