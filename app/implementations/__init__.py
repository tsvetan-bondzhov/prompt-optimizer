"""User-supplied reference implementations (executor, evaluation steps, etc.).

Importing this package triggers the import side effects of its modules, each of
which registers its reference implementation with the registry (the executor
under ``("executor", "default")`` and ``prepare_evaluation`` under
``("evaluation_prepare", "default")``). :func:`app.core.bootstrap.register_builtins`
imports this package so the registrations fire at startup.
"""

from __future__ import annotations

# Import for registration side effects. Order matters: ``prepare`` imports the
# step classes from ``evaluation_steps``.
from app.implementations import evaluation_steps, executor, prepare  # noqa: F401

__all__ = ["evaluation_steps", "executor", "prepare"]
