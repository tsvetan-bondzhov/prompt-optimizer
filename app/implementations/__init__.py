"""User-supplied reference implementations (executor, graders, etc.).

Importing this package triggers the import side effects of its modules, each of
which registers its reference implementation with the registry (the executor
under ``("executor", "default")`` and ``prepare_graders`` under
``("grader_prepare", "default")``). :func:`app.core.bootstrap.register_builtins`
imports this package so the registrations fire at startup.
"""

from __future__ import annotations

# Import for registration side effects. Order matters: ``prepare`` imports the
# step classes from ``graders``.
from app.implementations import (  # noqa: F401
    graders,
    executor,
    json_graders,
    ollama_executor,
    prepare,
)

__all__ = [
    "graders",
    "executor",
    "json_graders",
    "ollama_executor",
    "prepare",
]
