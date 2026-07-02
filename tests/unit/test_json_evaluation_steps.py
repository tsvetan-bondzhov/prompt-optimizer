"""Unit tests: JSON schema validation + expected-JSON match steps."""

from __future__ import annotations

import json

from app.implementations.json_evaluation_steps import (
    JsonExpectedMatchStep,
    JsonSchemaValidationStep,
    parse_json_result,
)
from app.models import PromptResult, TestCase


def make_case(criteria: dict) -> TestCase:
    return TestCase(name="tc", evaluation_criteria=criteria)


def result_of(value) -> PromptResult:
    return PromptResult(text=json.dumps(value))


SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer", "minimum": 0},
    },
    "required": ["name", "age"],
}

FENCED = '```json\n{"name": "Ada", "age": 36}\n```'


# -- parse_json_result -------------------------------------------------------


def test_parse_json_pure_by_default():
    value, error = parse_json_result('{"a": 1}')
    assert error is None
    assert value == {"a": 1}


def test_parse_json_rejects_fence_by_default():
    value, error = parse_json_result('```json\n{"a": 1}\n```')
    assert value is None
    assert error


def test_parse_json_unwraps_fence_when_allowed():
    value, error = parse_json_result('```json\n{"a": 1}\n```', allow_fence=True)
    assert error is None
    assert value == {"a": 1}


# -- Markdown fence configuration ---------------------------------------------


async def test_fenced_output_scores_1_by_default():
    step = JsonSchemaValidationStep()
    evaluation = await step.evaluate(
        PromptResult(text=FENCED), make_case({"json_schema": SCHEMA})
    )
    assert evaluation.score == 1
    assert any("Markdown" in w for w in evaluation.weaknesses)


async def test_fenced_output_accepted_when_enabled():
    step = JsonSchemaValidationStep(allow_markdown_fence=True)
    evaluation = await step.evaluate(
        PromptResult(text=FENCED), make_case({"json_schema": SCHEMA})
    )
    assert evaluation.score == 10


async def test_fence_setting_from_environment(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("JSON_EVAL_ALLOW_MARKDOWN", "true")
    get_settings.cache_clear()
    try:
        evaluation = await JsonSchemaValidationStep().evaluate(
            PromptResult(text=FENCED), make_case({"json_schema": SCHEMA})
        )
        assert evaluation.score == 10
    finally:
        get_settings.cache_clear()


# -- JsonSchemaValidationStep -------------------------------------------------


async def test_schema_valid_output_scores_10():
    step = JsonSchemaValidationStep()
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "age": 36}), make_case({"json_schema": SCHEMA})
    )
    assert evaluation.score == 10
    assert evaluation.step_name == "json_schema"


async def test_schema_violations_lower_score():
    step = JsonSchemaValidationStep()
    # age has the wrong type -> one violation.
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "age": "old"}), make_case({"json_schema": SCHEMA})
    )
    assert evaluation.score == 7
    assert any("age" in w for w in evaluation.weaknesses)


async def test_schema_unparseable_output_scores_1():
    step = JsonSchemaValidationStep()
    evaluation = await step.evaluate(
        PromptResult(text="oops"), make_case({"json_schema": SCHEMA})
    )
    assert evaluation.score == 1


async def test_schema_missing_config_is_neutral():
    evaluation = await JsonSchemaValidationStep().evaluate(
        result_of({}), make_case({})
    )
    assert evaluation.score == 5


# -- JsonExpectedMatchStep ------------------------------------------------------


async def test_expected_full_match_scores_10():
    step = JsonExpectedMatchStep()
    expected = {"name": "Ada", "role": {"title": "engineer"}}
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "role": {"title": "engineer"}, "extra": 1}),
        make_case({"expected_json": expected}),
    )
    assert evaluation.score == 10


async def test_expected_null_fields_are_ignored():
    step = JsonExpectedMatchStep()
    # "city" is null in the EXPECTED object -> ignored, whatever the output has.
    expected = {"name": "Ada", "city": None}
    evaluation = await step.evaluate(
        result_of({"name": "Ada"}), make_case({"expected_json": expected})
    )
    assert evaluation.score == 10
    assert "1 field(s) ignored" in evaluation.reasoning


async def test_missing_or_null_in_output_is_mismatch():
    step = JsonExpectedMatchStep()
    expected = {"name": "Ada", "age": 36, "city": "London"}
    # name matches; age missing in output; city null in output -> 2 mismatches.
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "city": None}),
        make_case({"expected_json": expected}),
    )
    # 1/3 matched -> 1 + 9/3 = 4.
    assert evaluation.score == 4
    assert any("$.age" in w for w in evaluation.weaknesses)
    assert any("$.city" in w for w in evaluation.weaknesses)


async def test_expected_mismatch_percentage_scoring():
    step = JsonExpectedMatchStep()
    expected = {"a": 1, "b": 2}
    # a matches, b mismatches -> 50% -> 1 + 0.5 * 9 = 5.5 -> 6 (round).
    evaluation = await step.evaluate(
        result_of({"a": 1, "b": 3}), make_case({"expected_json": expected})
    )
    assert evaluation.score == 6
    assert any("$.b" in w for w in evaluation.weaknesses)


async def test_expected_all_null_is_neutral():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({"a": 1}), make_case({"expected_json": {"a": None, "b": None}})
    )
    assert evaluation.score == 5


async def test_expected_unparseable_and_non_object_score_1():
    step = JsonExpectedMatchStep()
    case = make_case({"expected_json": {"a": 1}})
    assert (await step.evaluate(PromptResult(text="oops"), case)).score == 1
    assert (await step.evaluate(result_of([1, 2]), case)).score == 1


async def test_expected_nested_type_mismatch():
    step = JsonExpectedMatchStep()
    # expected dict, actual scalar at role -> mismatch.
    evaluation = await step.evaluate(
        result_of({"role": "engineer"}),
        make_case({"expected_json": {"role": {"title": "engineer"}}}),
    )
    assert evaluation.score == 1


async def test_expected_nested_null_ignored_inside_object():
    step = JsonExpectedMatchStep()
    expected = {"role": {"title": "engineer", "level": None}}
    evaluation = await step.evaluate(
        result_of({"role": {"title": "engineer"}}),
        make_case({"expected_json": expected}),
    )
    assert evaluation.score == 10
