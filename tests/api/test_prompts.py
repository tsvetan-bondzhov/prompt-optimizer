"""API tests: prompt management (Task 15)."""

from __future__ import annotations


def _make_test_case(client, name="tc"):
    return client.post(
        "/api/test-cases",
        json={"name": name, "data": [], "grader_names": ["fake"]},
    ).json()


def test_prompt_crud_roundtrip(client):
    tc = _make_test_case(client)
    r = client.post(
        "/api/prompts",
        json={
            "name": "concise-prompt",
            "goal": "be concise",
            "current_prompt": "Answer briefly.",
            "test_case_ids": [tc["id"]],
        },
    )
    assert r.status_code == 201
    prompt = r.json()
    assert prompt["avg_score"] is None

    assert client.get(f"/api/prompts/{prompt['id']}").status_code == 200
    assert len(client.get("/api/prompts").json()) == 1

    r = client.put(f"/api/prompts/{prompt['id']}", json={"goal": "be very concise"})
    assert r.json()["goal"] == "be very concise"

    assert client.delete(f"/api/prompts/{prompt['id']}").status_code == 204
    assert client.get(f"/api/prompts/{prompt['id']}").status_code == 404


def test_prompt_rejects_unknown_test_cases(client):
    r = client.post(
        "/api/prompts",
        json={
            "name": "p1",
            "goal": "g",
            "current_prompt": "p",
            "test_case_ids": ["missing"],
        },
    )
    assert r.status_code == 400


def test_prompt_versions_listing(client):
    prompt = client.post(
        "/api/prompts", json={"name": "p1", "goal": "g", "current_prompt": "p"}
    ).json()

    r = client.get(f"/api/prompts/{prompt['id']}/versions")
    assert r.status_code == 200
    assert r.json() == []

    assert client.get("/api/prompts/missing/versions").status_code == 404
    assert (
        client.get(f"/api/prompts/{prompt['id']}/versions/missing").status_code
        == 404
    )


def test_editing_prompt_resets_score(client):
    prompt = client.post(
        "/api/prompts", json={"name": "p1", "goal": "g", "current_prompt": "old"}
    ).json()

    r = client.put(f"/api/prompts/{prompt['id']}", json={"current_prompt": "new"})
    body = r.json()
    assert body["current_prompt"] == "new"
    assert body["avg_score"] is None
    assert body["strengths"] == []
