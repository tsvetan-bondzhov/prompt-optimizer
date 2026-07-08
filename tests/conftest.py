"""Shared test fixtures (Task 15).

Every test gets a fresh mongomock database. API tests get a ``TestClient``
whose registry resolves to deterministic fakes (no LLM / network access): the
fake executor, a scripted evaluation step, the fake optimizer, and the fake
summarizer are (re-)registered under the *active* configuration names before
each test.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.core.bootstrap import register_builtins
from app.core.registry import register
from app.llm.fake import FakeLLMRunner
from tests.fakes import (
    FakeGrader,
    FakeExecutor,
    FakeOptimizer,
    FakeSummarizer,
)


@pytest.fixture
def db():
    """A fresh mongomock database per test."""

    return AsyncMongoMockClient()[f"test_{uuid.uuid4().hex}"]


@pytest.fixture(autouse=True)
def registered_fakes():
    """Point every active registry name at a deterministic fake.

    ``register`` overwrites previous factories, so this shadows the reference
    implementations registered by ``register_builtins`` for the duration of the
    test session (each test re-registers, so per-test customization is safe).
    """

    register_builtins()
    register("executor", "default", FakeExecutor)
    register("grader", "fake", lambda: FakeGrader(scores=(8,)))
    register("optimizer", "claude_code", FakeOptimizer)
    register("summarizer", "default", FakeSummarizer)
    register("llm_runner", "claude_code", FakeLLMRunner)
    yield


@pytest.fixture
def client(db):
    """A TestClient running the full app against the mongomock database."""

    from app.main import create_app

    app = create_app(database=db)
    with TestClient(app) as test_client:
        yield test_client
