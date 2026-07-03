"""Unit tests: model validation + aggregation math (Task 15)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.interfaces import mean_aggregator
from app.models import PromptEvaluation, RunConfig, TestCaseCreate


def _evaluation(score: int) -> PromptEvaluation:
    return PromptEvaluation(
        strengths=["s"], weaknesses=["w"], reasoning="r", score=score
    )


def test_score_bounds_enforced():
    for score in (0, 11, -1):
        with pytest.raises(ValidationError):
            _evaluation(score)
    assert _evaluation(1).score == 1
    assert _evaluation(10).score == 10


def test_strengths_weaknesses_bounds():
    with pytest.raises(ValidationError):
        PromptEvaluation(strengths=[], weaknesses=["w"], reasoning="r", score=5)
    with pytest.raises(ValidationError):
        PromptEvaluation(
            strengths=["a", "b", "c", "d"], weaknesses=["w"], reasoning="r", score=5
        )
    with pytest.raises(ValidationError):
        PromptEvaluation(strengths=["  "], weaknesses=["w"], reasoning="r", score=5)


def test_reasoning_must_be_non_empty():
    with pytest.raises(ValidationError):
        PromptEvaluation(strengths=["s"], weaknesses=["w"], reasoning="  ", score=5)


def test_mean_aggregator():
    assert mean_aggregator([]) == 0.0
    assert mean_aggregator([_evaluation(4), _evaluation(8)]) == 6.0
    assert mean_aggregator([_evaluation(7)]) == 7.0


def test_run_config_bounds():
    with pytest.raises(ValidationError):
        RunConfig(target_score=11)
    with pytest.raises(ValidationError):
        RunConfig(max_iterations=0)
    with pytest.raises(ValidationError):
        RunConfig(executions_per_test_case=0)


def test_test_case_create_requires_name():
    with pytest.raises(ValidationError):
        TestCaseCreate(name="")


def test_test_case_data_coerces_legacy_object():
    tc = TestCaseCreate(name="tc", data={"input": "x"})
    assert tc.data == [{"input": "x"}]


def test_criteria_fallback_per_entry_then_dataset():
    from app.models import TestCase

    tc = TestCase(
        name="tc",
        data=[{"a": 1}, {"a": 2}, {"a": 3}],
        evaluation_criteria_per_entry=[{"keywords": ["one"]}, {}],
        evaluation_criteria={"keywords": ["fallback"]},
    )
    assert tc.criteria_for_entry(0) == {"keywords": ["one"]}
    # Empty per-entry criteria falls back to the dataset criteria.
    assert tc.criteria_for_entry(1) == {"keywords": ["fallback"]}
    # Missing per-entry criteria (index out of range) falls back too.
    assert tc.criteria_for_entry(2) == {"keywords": ["fallback"]}
