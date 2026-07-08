"""Graders omit filler strengths/weaknesses that carry no information."""

from __future__ import annotations

import json

from app.implementations.graders import KeywordCoverageGrader
from app.implementations.json_graders import JsonSchemaValidationGrader
from app.implementations.word_count_grader import WordCountGrader
from app.models import PromptResult, TestCase

SCHEMA = {"type": "object", "required": ["name"]}


def case(criteria: dict) -> TestCase:
    return TestCase(name="tc", grader_names=["x"], evaluation_criteria=criteria)


async def test_keyword_full_match_has_no_weaknesses():
    evaluation = await KeywordCoverageGrader().grade(
        PromptResult(text="alpha beta"), case({"keywords": ["alpha", "beta"]})
    )
    assert evaluation.score == 10
    assert evaluation.weaknesses == []


async def test_keyword_no_match_has_no_strengths():
    evaluation = await KeywordCoverageGrader().grade(
        PromptResult(text="nothing here"), case({"keywords": ["absent"]})
    )
    assert evaluation.score == 1
    assert evaluation.strengths == []


async def test_schema_valid_output_has_no_weaknesses():
    evaluation = await JsonSchemaValidationGrader().grade(
        PromptResult(text=json.dumps({"name": "Ada"})),
        case({"json_schema": SCHEMA}),
    )
    assert evaluation.score == 10
    assert evaluation.weaknesses == []


async def test_schema_parse_failure_has_no_strengths():
    evaluation = await JsonSchemaValidationGrader().grade(
        PromptResult(text="not json"), case({"json_schema": SCHEMA})
    )
    assert evaluation.score == 1
    assert evaluation.strengths == []


async def test_word_count_pass_has_no_weaknesses_and_fail_no_strengths():
    result = PromptResult(text="one two three", prompt_text="p")
    passed = await WordCountGrader().grade(result, case({"word_count": {"eq": 3}}))
    assert passed.score == 10 and passed.weaknesses == []
    failed = await WordCountGrader().grade(result, case({"word_count": {"eq": 4}}))
    assert failed.score == 1 and failed.strengths == []
