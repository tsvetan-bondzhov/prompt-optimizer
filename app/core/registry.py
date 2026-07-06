"""Implementation registry + settings-driven resolvers (see plan §4.1).

Concrete implementations register a *factory* (a zero-argument callable that
returns an instance, e.g. the class itself) under a ``(category, name)`` key.
Services then resolve the *active* implementation by name from
:class:`app.config.Settings`.

Categories:
    ``executor``            -> :class:`~app.core.interfaces.PromptExecutor`
    ``grader``              -> :class:`~app.core.interfaces.Grader`
    ``optimizer``            -> :class:`~app.core.interfaces.PromptOptimizer`
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
    Grader,
    LLMRunner,
    PromptExecutor,
    PromptOptimizer,
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
    "describe",
    "clear",
    "get_executor",
    "get_grader",
    "get_prompt_optimizer",
    "get_summarizer",
    "get_llm_runner",
    "get_aggregator",
]

# A factory is any zero-arg callable returning an instance (a class works too).
Factory = Callable[[], Any]

CATEGORIES: tuple[str, ...] = (
    "executor",
    "grader",
    "optimizer",
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


def describe(category: str) -> list[dict[str, Any]]:
    """Return UI metadata for every implementation registered in ``category``.

    Each item: ``{"name", "display_name", "description", "criteria_info",
    "criteria_sample", "options_schema"}`` — read from the instantiated
    implementation's class attributes, with sensible fallbacks so
    implementations without metadata still render.
    """

    infos: list[dict[str, Any]] = []
    for name in available(category):
        try:
            instance = resolve(category, name)
        except Exception:  # pragma: no cover - defensive: bad factory
            infos.append({"name": name, "display_name": name})
            continue
        infos.append(
            {
                "name": name,
                "display_name": getattr(instance, "display_name", "") or name,
                "description": getattr(instance, "description", "") or "",
                "criteria_info": list(getattr(instance, "criteria_info", []) or []),
                "criteria_sample": getattr(instance, "criteria_sample", None),
                "options_schema": list(
                    getattr(instance, "options_schema", []) or []
                ),
            }
        )
    return infos


def clear(category: str | None = None) -> None:
    """Clear registrations for ``category`` (or all categories when ``None``)."""

    if category is None:
        for bucket in _REGISTRY.values():
            bucket.clear()
        return
    _check_category(category)
    _REGISTRY[category].clear()


# --- Settings-driven resolver helpers ------------------------------------


def get_executor(name: str | None = None) -> PromptExecutor:
    """Resolve a :class:`PromptExecutor` by ``name`` (active one when omitted)."""

    return resolve("executor", name or get_settings().ACTIVE_EXECUTOR)


def get_grader(name: str) -> Grader:
    """Resolve a :class:`Grader` registered under ``name``.

    Graders are selected **per test case** (``TestCase.grader_names``); use
    :func:`available` with the ``"grader"`` category to list the choices.
    """

    return resolve("grader", name)


def get_prompt_optimizer() -> PromptOptimizer:
    """Resolve the active :class:`PromptOptimizer` from settings."""

    return resolve("optimizer", get_settings().ACTIVE_OPTIMIZER)


def get_summarizer() -> Summarizer:
    """Resolve the active :class:`Summarizer` from settings."""

    return resolve("summarizer", get_settings().ACTIVE_SUMMARIZER)


def get_llm_runner(name: str | None = None) -> LLMRunner:
    """Resolve an :class:`LLMRunner` by ``name`` (active one when omitted)."""

    return resolve("llm_runner", name or get_settings().ACTIVE_LLM_RUNNER)


def get_aggregator() -> Aggregator:
    """Resolve the active :class:`Aggregator`, defaulting to the mean strategy."""

    bucket = _REGISTRY["aggregator"]
    if not bucket:
        return mean_aggregator
    name = getattr(get_settings(), "ACTIVE_AGGREGATOR", "default")
    if name not in bucket:
        return mean_aggregator
    return resolve("aggregator", name)
