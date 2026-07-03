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
        result_of({"name": "Ada", "role": {"title": "engineer"}}),
        make_case({"expected_json": expected}),
    )
    assert evaluation.score == 10


async def test_unexpected_output_fields_are_mismatches():
    step = JsonExpectedMatchStep()
    expected = {"name": "Ada"}
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "extra": 1}),
        make_case({"expected_json": expected}),
    )
    # name matched, extra unexpected -> 1/2 -> 1 + 4.5 -> 6.
    assert evaluation.score == 6
    assert any(
        "$.extra" in w and "unexpected" in w for w in evaluation.weaknesses
    )


async def test_unexpected_null_output_field_is_ignored():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({"name": "Ada", "extra": None}),
        make_case({"expected_json": {"name": "Ada"}}),
    )
    # extra is null in the output and missing in expected -> ignored.
    assert evaluation.score == 10


async def test_expected_null_with_output_value_is_mismatch():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({"a": 1, "b": 2}),
        make_case({"expected_json": {"a": 1, "b": None}}),
    )
    # a matched; b expected null but output has a value -> 1/2 -> 6.
    assert evaluation.score == 6
    assert any("$.b" in w and "expected null" in w for w in evaluation.weaknesses)


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


async def test_nothing_comparable_is_neutral():
    step = JsonExpectedMatchStep()
    # Both sides null/missing everywhere -> everything ignored -> neutral.
    evaluation = await step.evaluate(
        result_of({"a": None}), make_case({"expected_json": {"a": None, "b": None}})
    )
    assert evaluation.score == 5


async def test_arrays_of_objects_compared_element_wise():
    step = JsonExpectedMatchStep()
    expected = {
        "items": [
            {"sku": "A", "qty": 1},
            {"sku": "B", "qty": 2},
        ]
    }
    # First element matches fully; second has a wrong qty -> 3/4 matched.
    evaluation = await step.evaluate(
        result_of({"items": [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 99}]}),
        make_case({"expected_json": expected}),
    )
    # 3/4 -> 1 + 6.75 = 7.75 -> 8.
    assert evaluation.score == 8
    assert any("$.items[1].qty" in w for w in evaluation.weaknesses)


async def test_array_length_mismatch_flagged():
    step = JsonExpectedMatchStep()
    expected = {"tags": ["a", "b"]}
    # Missing second element -> mismatch at $.tags[1]; extra third would too.
    evaluation = await step.evaluate(
        result_of({"tags": ["a"]}), make_case({"expected_json": expected})
    )
    assert evaluation.score == 6  # 1/2 matched
    assert any("$.tags[1]" in w for w in evaluation.weaknesses)


async def test_array_extra_element_flagged_as_unexpected():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({"tags": ["a", "b"]}),
        make_case({"expected_json": {"tags": ["a"]}}),
    )
    assert evaluation.score == 6  # 1/2 matched
    assert any(
        "$.tags[1]" in w and "unexpected" in w for w in evaluation.weaknesses
    )


async def test_array_vs_non_array_is_mismatch():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({"tags": "a,b"}), make_case({"expected_json": {"tags": ["a"]}})
    )
    assert evaluation.score == 1
    assert any("expected an array" in w for w in evaluation.weaknesses)


async def test_top_level_array_full_match_scores_10():
    step = JsonExpectedMatchStep()
    expected = [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 2}]
    evaluation = await step.evaluate(
        result_of([{"sku": "A", "qty": 1}, {"sku": "B", "qty": 2}]),
        make_case({"expected_json": expected}),
    )
    assert evaluation.score == 10


async def test_top_level_array_partial_match():
    step = JsonExpectedMatchStep()
    # First element matches, second does not -> 1/2 -> 6.
    evaluation = await step.evaluate(
        result_of(["a", "x"]), make_case({"expected_json": ["a", "b"]})
    )
    assert evaluation.score == 6
    assert any("$[1]" in w for w in evaluation.weaknesses)


async def test_top_level_array_expected_but_object_output_scores_1():
    step = JsonExpectedMatchStep()
    evaluation = await step.evaluate(
        result_of({"a": 1}), make_case({"expected_json": [1, 2]})
    )
    assert evaluation.score == 1
    assert any("not a JSON array" in w for w in evaluation.weaknesses)


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
