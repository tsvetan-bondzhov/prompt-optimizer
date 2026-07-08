"""User-supplied reference implementations (executor, graders, etc.).

Importing this package triggers the import side effects of its modules, each of
which registers its reference implementation with the registry (the executor
under ``("executor", "default")`` and the graders under the ``grader``
category). :func:`app.core.bootstrap.register_builtins`
imports this package so the registrations fire at startup.
"""

from __future__ import annotations

# Import for registration side effects: each module registers its
# implementations (executors, graders) with the registry.
from app.implementations import (  # noqa: F401
    executor,
    graders,
    json_graders,
    model_grader,
    simple_executors,
    template_executor,
    tiktoken_grader,
    word_count_grader,
)

__all__ = [
    "executor",
    "graders",
    "json_graders",
    "model_grader",
    "simple_executors",
    "template_executor",
    "tiktoken_grader",
    "word_count_grader",
]
