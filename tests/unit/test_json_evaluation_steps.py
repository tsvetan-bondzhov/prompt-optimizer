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


# -- parse_json_result -------------------------------------------------------


def test_parse_json_unwraps_code_fence():
    value, error = parse_json_result('```json\n{"a": 1}\n```')
    assert error is None
    assert value == {"a": 1}


def test_parse_json_reports_error():
    value, error = parse_json_result("not json")
    assert value is None
    assert error


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


async def test_expected_missing_and_null_fields_are_ignored():
    step = JsonExpectedMatchStep()
    expected = {"name": "Ada", "age": 36, "city": "London"}
    # age missing, city null -> ignored; name matches -> 100% of compared.
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "city": None}),
        make_case({"expected_json": expected}),
    )
    assert evaluation.score == 10
    assert "2 field(s) ignored" in evaluation.reasoning


async def test_expected_mismatch_percentage_scoring():
    step = JsonExpectedMatchStep()
    expected = {"a": 1, "b": 2}
    # a matches, b mismatches -> 50% -> 1 + 0.5 * 9 = 5.5 -> 6 (round).
    evaluation = await step.evaluate(
        result_of({"a": 1, "b": 3}), make_case({"expected_json": expected})
    )
    assert evaluation.score == 6
    assert any("$.b" in w for w in evaluation.weaknesses)


async def test_expected_nothing_comparable_is_neutral():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({}), make_case({"expected_json": {"a": 1, "b": 2}})
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
