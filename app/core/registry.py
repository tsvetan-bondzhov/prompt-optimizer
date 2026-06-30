"""Implementation registry + settings-driven resolvers (see plan §4.1).

Concrete implementations register a *factory* (a zero-argument callable that
returns an instance, e.g. the class itself) under a ``(category, name)`` key.
Services then resolve the *active* implementation by name from
:class:`app.config.Settings`.

Categories:
    ``executor``            -> :class:`~app.core.interfaces.PromptExecutor`
    ``evaluation_prepare``  -> :class:`~app.core.interfaces.PrepareEvaluation`
    ``improver``            -> :class:`~app.core.interfaces.PromptImprover`
    ``summarizer``          -> :class:`~app.core.interfaces.Summarizer`
    ``llm_runner``          -> :class:`~app.core.interfaces.LLMRunner`
    ``aggregator``          -> :class:`~app.core.interfaces.Aggregator`

Resolution raises :class:`UnknownImplementationError` with the list of available
names when a configured name is not registered.
"""

from __future__ import annotations

from typing import Any, Callable

from app.config import get_settings
from app.core.interfaces import (
    Aggregator,
    EvaluationStep,
    LLMRunner,
    PromptExecutor,
    PromptImprover,
    Summarizer,
    mean_aggregator,
)

__all__ = [
    "RegistryError",
    "UnknownImplementationError",
    "UnknownCategoryError",
    "register",
    "resolve",
    "available",
    "clear",
    "get_executor",
    "get_evaluation_steps",
    "get_improver",
    "get_summarizer",
    "get_llm_runner",
    "get_aggregator",
]

# A factory is any zero-arg callable returning an instance (a class works too).
Factory = Callable[[], Any]

CATEGORIES: tuple[str, ...] = (
    "executor",
    "evaluation_prepare",
    "improver",
    "summarizer",
    "llm_runner",
    "aggregator",
)

# category -> {name -> factory}
_REGISTRY: dict[str, dict[str, Factory]] = {category: {} for category in CATEGORIES}


class RegistryError(Exception):
    """Base class for registry errors."""


class UnknownCategoryError(RegistryError):
    """Raised when an unknown category is used."""

    def __init__(self, category: str) -> None:
        known = ", ".join(CATEGORIES)
        super().__init__(
            f"Unknown registry category {category!r}. Known categories: {known}."
        )


class UnknownImplementationError(RegistryError):
    """Raised when a configured implementation name is not registered."""

    def __init__(self, category: str, name: str, available_names: list[str]) -> None:
        names = ", ".join(sorted(available_names)) or "<none registered>"
        super().__init__(
            f"No implementation named {name!r} registered for category "
            f"{category!r}. Available: {names}."
        )


def _check_category(category: str) -> None:
    if category not in _REGISTRY:
        raise UnknownCategoryError(category)


def register(category: str, name: str, factory: Factory) -> None:
    """Register ``factory`` under ``(category, name)``.

    Re-registering the same name overwrites the previous factory (useful for
    tests). Raises :class:`UnknownCategoryError` for an unknown category.
    """

    _check_category(category)
    _REGISTRY[category][name] = factory


def resolve(category: str, name: str) -> Any:
    """Instantiate and return the implementation registered as ``(category, name)``.

    Raises :class:`UnknownImplementationError` (listing available names) when the
    name is not registered.
    """

    _check_category(category)
    bucket = _REGISTRY[category]
    try:
        factory = bucket[name]
    except KeyError:
        raise UnknownImplementationError(category, name, list(bucket)) from None
    return factory()


def available(category: str) -> list[str]:
    """Return the sorted list of registered names for ``category``."""

    _check_category(category)
    return sorted(_REGISTRY[category])


def clear(category: str | None = None) -> None:
    """Clear registrations for ``category`` (or all categories when ``None``)."""

    if category is None:
        for bucket in _REGISTRY.values():
            bucket.clear()
        return
    _check_category(category)
    _REGISTRY[category].clear()


# --- Settings-driven resolver helpers ------------------------------------


def get_executor() -> PromptExecutor:
    """Resolve the active :class:`PromptExecutor` from settings."""

    return resolve("executor", get_settings().ACTIVE_EXECUTOR)


def get_evaluation_steps() -> list[EvaluationStep]:
    """Call the active ``prepare_evaluation()`` factory and return its steps.

    The active prepare key reuses ``ACTIVE_EXECUTOR`` since the executor and the
    evaluation steps form a matched user-supplied pair.
    """

    # The registered factory IS ``prepare_evaluation``; resolving it invokes the
    # factory, which returns the ordered list of EvaluationStep instances.
    steps = resolve("evaluation_prepare", get_settings().ACTIVE_EXECUTOR)
    return steps


def get_improver() -> PromptImprover:
    """Resolve the active :class:`PromptImprover` from settings."""

    return resolve("improver", get_settings().ACTIVE_IMPROVER)


def get_summarizer() -> Summarizer:
    """Resolve the active :class:`Summarizer` from settings."""

    return resolve("summarizer", get_settings().ACTIVE_SUMMARIZER)


def get_llm_runner() -> LLMRunner:
    """Resolve the active :class:`LLMRunner` from settings."""

    return resolve("llm_runner", get_settings().ACTIVE_LLM_RUNNER)


def get_aggregator() -> Aggregator:
    """Resolve the active :class:`Aggregator`, defaulting to the mean strategy."""

    bucket = _REGISTRY["aggregator"]
    if not bucket:
        return mean_aggregator
    name = getattr(get_settings(), "ACTIVE_AGGREGATOR", "default")
    if name not in bucket:
        return mean_aggregator
    return resolve("aggregator", name)
