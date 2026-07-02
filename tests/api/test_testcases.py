"""API tests: test case CRUD + bulk import (Task 15)."""

from __future__ import annotations


def test_crud_roundtrip(client):
    # create
    r = client.post(
        "/api/test-cases",
        json={
            "name": "tc1",
            "data": {"input": "hello"},
            "evaluation_criteria": {"keywords": ["hello"]},
        },
    )
    assert r.status_code == 201
    tc = r.json()
    assert tc["name"] == "tc1"
    assert tc["id"]

    # get
    assert client.get(f"/api/test-cases/{tc['id']}").json()["name"] == "tc1"

    # list
    assert len(client.get("/api/test-cases").json()) == 1

    # update
    r = client.put(
        f"/api/test-cases/{tc['id']}",
        json={"name": "tc1-renamed", "data": {}, "evaluation_criteria": {}},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "tc1-renamed"

    # delete
    assert client.delete(f"/api/test-cases/{tc['id']}").status_code == 204
    assert client.get(f"/api/test-cases/{tc['id']}").status_code == 404


def test_bulk_import(client):
    r = client.post(
        "/api/test-cases/import",
        json=[
            {"name": "a", "data": {}, "evaluation_criteria": {}},
            {"name": "b", "data": {}, "evaluation_criteria": {}},
        ],
    )
    assert r.status_code == 201
    assert len(r.json()) == 2
    assert len(client.get("/api/test-cases").json()) == 2


def test_import_rejects_empty_payload(client):
    assert client.post("/api/test-cases/import", json=[]).status_code == 400


def test_validation_rejects_blank_name(client):
    r = client.post("/api/test-cases", json={"name": ""})
    assert r.status_code == 422


def test_unknown_id_is_404(client):
    assert client.get("/api/test-cases/nope").status_code == 404
    assert client.delete("/api/test-cases/nope").status_code == 404
