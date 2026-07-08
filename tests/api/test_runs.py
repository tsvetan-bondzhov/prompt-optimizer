"""API tests: run-start endpoints, report/step listings, SSE smoke (Task 15).

Background tasks scheduled by the routes run to completion before the
TestClient returns the response, so runs are terminal by the time we assert.
"""

from __future__ import annotations

REPORT_FIELDS = {
    "date",
    "test_case_id",
    "prompt",
    "prompt_result",
    "score",
    "strengths",
    "weaknesses",
    "reasoning",
}

STEP_FIELDS = {
    "previous_prompt",
    "proposed_prompt",
    "previous_avg_score",
    "new_avg_score",
    "summarized_reasoning",
    "test_case_ids",
    "evaluation_report_ids",
    "accepted",
    "iteration_index",
}


def _setup_prompt(client):
    tc = client.post(
        "/api/test-cases",
        json={
            "name": "tc",
            "data": [{"input": "x"}],
            "grader_names": ["fake"],
        },
    ).json()
    prompt = client.post(
        "/api/prompts",
        json={
            "name": "prompt-under-test",
            "goal": "goal",
            "current_prompt": "base prompt",
            "test_case_ids": [tc["id"]],
        },
    ).json()
    return tc, prompt


def test_start_evaluation_returns_run_id_and_produces_reports(client):
    tc, _ = _setup_prompt(client)
    r = client.post(
        "/api/evaluations",
        json={
            "prompt": "evaluate me",
            "test_case_ids": [tc["id"]],
            "executions_per_test_case": 2,
        },
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert run_id

    run = client.get(f"/api/evaluations/{run_id}").json()
    assert run["status"] == "completed"
    assert run["avg_score"] is not None

    reports = client.get(f"/api/evaluations/{run_id}/reports").json()
    assert len(reports) == 2  # 1 test case × N=2
    assert REPORT_FIELDS.issubset(reports[0].keys())


def test_start_evaluation_from_state(client):
    _, prompt = _setup_prompt(client)
    r = client.post("/api/evaluations", json={"prompt_id": prompt["id"]})
    assert r.status_code == 202
    run = client.get(f"/api/evaluations/{r.json()['run_id']}").json()
    assert run["prompt"] == "base prompt"


def test_start_evaluation_requires_prompt_and_test_cases(client):
    assert (
        client.post("/api/evaluations", json={"prompt": "p"}).status_code == 400
    )
    assert (
        client.post("/api/evaluations", json={"test_case_ids": []}).status_code
        == 400
    )


def test_start_optimization_returns_run_id_and_persists_steps(client):
    _, prompt = _setup_prompt(client)
    r = client.post(
        "/api/optimizations",
        json={
            "prompt_id": prompt["id"],
            "config": {
                "target_score": 9.5,
                "max_iterations": 2,
                "executions_per_test_case": 1,
            },
        },
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    run = client.get(f"/api/optimizations/{run_id}").json()
    assert run["status"] == "completed"

    steps = client.get(f"/api/optimizations/{run_id}/steps").json()
    assert steps, "expected at least one optimization step"
    assert STEP_FIELDS.issubset(steps[0].keys())

    # step detail + linked report detail round-trip
    step = client.get(f"/api/steps/{steps[0]['id']}").json()
    assert step["run_id"] == run_id
    report_id = step["evaluation_report_ids"][0]
    report = client.get(f"/api/reports/{report_id}").json()
    assert REPORT_FIELDS.issubset(report.keys())


def test_start_optimization_rejects_bad_state(client):
    r = client.post("/api/optimizations", json={"prompt_id": "missing"})
    assert r.status_code == 400

    # prompt without test cases
    prompt = client.post(
        "/api/prompts", json={"name": "p1", "goal": "g", "current_prompt": "p"}
    ).json()
    r = client.post("/api/optimizations", json={"prompt_id": prompt["id"]})
    assert r.status_code == 400


def test_sse_stream_sends_snapshot(client):
    tc, _ = _setup_prompt(client)
    run_id = client.post(
        "/api/evaluations",
        json={"prompt": "p", "test_case_ids": [tc["id"]]},
    ).json()["run_id"]

    with client.stream("GET", f"/api/progress/{run_id}/stream") as stream:
        assert stream.status_code == 200
        body = ""
        for chunk in stream.iter_text():
            body += chunk
            if "event: snapshot" in body:
                break
    assert "event: snapshot" in body
    assert run_id in body


def test_sse_stream_unknown_run_is_404(client):
    assert client.get("/api/progress/nope/stream").status_code == 404


def test_standalone_evaluation_updates_prompt_when_requested(client):
    _, prompt = _setup_prompt(client)
    assert prompt["avg_score"] is None

    r = client.post(
        "/api/evaluations",
        json={"prompt_id": prompt["id"], "update_prompt": True},
    )
    assert r.status_code == 202

    updated = client.get(f"/api/prompts/{prompt['id']}").json()
    assert updated["avg_score"] is not None
    assert updated["strengths"]
    assert updated["current_prompt"] == "base prompt"


def test_update_prompt_with_custom_text_replaces_current_prompt(client):
    _, prompt = _setup_prompt(client)
    r = client.post(
        "/api/evaluations",
        json={
            "prompt_id": prompt["id"],
            "prompt": "hand-tuned prompt",
            "update_prompt": True,
        },
    )
    assert r.status_code == 202

    updated = client.get(f"/api/prompts/{prompt['id']}").json()
    assert updated["current_prompt"] == "hand-tuned prompt"
    assert updated["avg_score"] is not None


def test_evaluation_without_update_leaves_prompt_untouched(client):
    _, prompt = _setup_prompt(client)
    client.post("/api/evaluations", json={"prompt_id": prompt["id"]})
    untouched = client.get(f"/api/prompts/{prompt['id']}").json()
    assert untouched["avg_score"] is None


def test_update_prompt_requires_prompt_id(client):
    tc, _ = _setup_prompt(client)
    r = client.post(
        "/api/evaluations",
        json={
            "prompt": "p",
            "test_case_ids": [tc["id"]],
            "update_prompt": True,
        },
    )
    assert r.status_code == 400
