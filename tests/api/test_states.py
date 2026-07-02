"""API tests: optimization state management (Task 15)."""

from __future__ import annotations


def _make_test_case(client, name="tc"):
    return client.post(
        "/api/test-cases",
        json={"name": name, "data": {}, "evaluation_criteria": {}},
    ).json()


def test_state_crud_roundtrip(client):
    tc = _make_test_case(client)
    r = client.post(
        "/api/states",
        json={
            "goal": "be concise",
            "current_prompt": "Answer briefly.",
            "test_case_ids": [tc["id"]],
        },
    )
    assert r.status_code == 201
    state = r.json()
    assert state["avg_score"] is None

    assert client.get(f"/api/states/{state['id']}").status_code == 200
    assert len(client.get("/api/states").json()) == 1

    r = client.put(f"/api/states/{state['id']}", json={"goal": "be very concise"})
    assert r.json()["goal"] == "be very concise"

    assert client.delete(f"/api/states/{state['id']}").status_code == 204
    assert client.get(f"/api/states/{state['id']}").status_code == 404


def test_state_rejects_unknown_test_cases(client):
    r = client.post(
        "/api/states",
        json={"goal": "g", "current_prompt": "p", "test_case_ids": ["missing"]},
    )
    assert r.status_code == 400


def test_editing_prompt_resets_score(client):
    state = client.post(
        "/api/states", json={"goal": "g", "current_prompt": "old"}
    ).json()

    r = client.put(f"/api/states/{state['id']}", json={"current_prompt": "new"})
    body = r.json()
    assert body["current_prompt"] == "new"
    assert body["avg_score"] is None
    assert body["strengths"] == []
