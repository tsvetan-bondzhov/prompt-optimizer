"""Shared factories for domain models.

Centralizes the ID strategy (string UUID4) and UTC timestamp creation so all
models stay consistent with the persistence layer
(:mod:`app.db.repositories.base`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """Return a fresh standardized identifier (string UUID4)."""

    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)
