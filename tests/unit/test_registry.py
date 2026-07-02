"""Unit tests: registry registration/resolution (Task 15)."""

from __future__ import annotations

import pytest

from app.core import registry


class _Impl:
    pass


def test_register_and_resolve_roundtrip():
    registry.register("executor", "unit-test-impl", _Impl)
    instance = registry.resolve("executor", "unit-test-impl")
    assert isinstance(instance, _Impl)
    assert "unit-test-impl" in registry.available("executor")


def test_resolve_unknown_name_lists_available():
    registry.register("executor", "unit-test-impl", _Impl)
    with pytest.raises(registry.UnknownImplementationError) as exc:
        registry.resolve("executor", "does-not-exist")
    assert "does-not-exist" in str(exc.value)
    assert "unit-test-impl" in str(exc.value)


def test_unknown_category_raises():
    with pytest.raises(registry.UnknownCategoryError):
        registry.register("nope", "x", _Impl)
    with pytest.raises(registry.UnknownCategoryError):
        registry.resolve("nope", "x")


def test_reregistering_overwrites():
    registry.register("executor", "unit-test-impl", _Impl)

    class Other:
        pass

    registry.register("executor", "unit-test-impl", Other)
    assert isinstance(registry.resolve("executor", "unit-test-impl"), Other)
