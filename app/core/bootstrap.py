"""Registration entry point for built-in/reference implementations (plan §4.1).

Call :func:`register_builtins` once at application startup to populate the
registry. It is idempotent.

This module only registers framework-provided defaults (currently the mean
aggregator). User-supplied / reference implementations — concrete
``PromptExecutor``, ``EvaluationStep`` + ``prepare_evaluation()``,
``PromptImprover``, ``Summarizer`` and ``LLMRunner`` — live under
``app/implementations`` and ``app/llm`` (Tasks 06/07/10). When those exist they
register themselves here (or via import side effects in
``app/implementations/__init__.py``).

Adding a new implementation (see Task 16 for the full guide):
    1. Implement the relevant ABC from :mod:`app.core.interfaces`.
    2. Register it: ``register("<category>", "<name>", Factory)``.
    3. Point the matching ``ACTIVE_*`` setting at ``"<name>"``.
"""

from __future__ import annotations

from app.core.interfaces import mean_aggregator
from app.core.registry import register

__all__ = ["register_builtins"]

_done = False


def register_builtins() -> None:
    """Register framework-provided default implementations (idempotent)."""

    global _done
    if _done:
        return

    # Default aggregation strategy: mean of per-step scores.
    register("aggregator", "default", lambda: mean_aggregator)

    # LLM runners (Task 06): the Claude Code headless runner is the default,
    # plus a deterministic fake runner for tests/offline development. Imported
    # lazily to keep import-time side effects out of the core package.
    from app.llm.claude_code import ClaudeCodeRunner
    from app.llm.fake import FakeLLMRunner

    register("llm_runner", "claude_code", ClaudeCodeRunner)
    register("llm_runner", "fake", FakeLLMRunner)

    # Reference implementations (Task 07): importing the package fires the
    # module-level registrations — the reference PromptExecutor under
    # ("executor", "default") and prepare_evaluation() under
    # ("evaluation_prepare", "default"). Imported lazily here to keep
    # import-time side effects out of the core package.
    import app.implementations  # noqa: F401

    # NOTE: reference improver / summarizer are registered by their own modules
    # (Task 10).

    _done = True
