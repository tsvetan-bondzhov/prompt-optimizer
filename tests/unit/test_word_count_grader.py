"""Unit tests: WordCountGrader conditions and modes."""

from __future__ import annotations

import pytest

from app.implementations.word_count_grader import WordCountGrader, count_words
from app.models import PromptResult, TestCase

# 4 prompt words, 6 response words.
RESULT = PromptResult(
    text="one two three four five six",
    prompt_text="alpha beta gamma delta",
)


def case(criteria: dict) -> TestCase:
    return TestCase(name="tc", grader_names=["word_count"], evaluation_criteria=criteria)


def test_count_words():
    assert count_words("") == 0
    assert count_words("  a   b\nc\t d ") == 4


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"eq": 6}, 10),
        ({"eq": 5}, 1),
        ({"gt": 5}, 10),
        ({"gt": 6}, 1),
        ({"lt": 7}, 10),
        ({"lt": 6}, 1),
        ({"gte": 6}, 10),
        ({"gte": 7}, 1),
        ({"lte": 6}, 10),
        ({"lte": 5}, 1),
        ({"gte": 5, "lte": 7}, 10),
        ({"gte": 5, "lte": 5}, 1),
    ],
)
async def test_response_mode_operators(condition, expected):
    evaluation = await WordCountGrader().grade(RESULT, case({"word_count": condition}))
    assert evaluation.score == expected


async def test_prompt_mode_counts_executed_prompt():
    evaluation = await WordCountGrader().grade(
        RESULT, case({"word_count": {"eq": 4, "mode": "prompt"}})
    )
    assert evaluation.score == 10


async def test_total_mode_counts_prompt_plus_response():
    evaluation = await WordCountGrader().grade(
        RESULT, case({"word_count": {"eq": 10, "mode": "total"}})
    )
    assert evaluation.score == 10


async def test_mode_via_word_count_mode_key():
    evaluation = await WordCountGrader().grade(
        RESULT, case({"word_count": {"eq": 4}, "word_count_mode": "prompt"})
    )
    assert evaluation.score == 10


async def test_mode_inside_condition_wins():
    evaluation = await WordCountGrader().grade(
        RESULT,
        case({"word_count": {"eq": 6, "mode": "response"}, "word_count_mode": "prompt"}),
    )
    assert evaluation.score == 10


async def test_missing_condition_is_neutral():
    evaluation = await WordCountGrader().grade(RESULT, case({}))
    assert evaluation.score == 5


async def test_unknown_mode_is_neutral():
    evaluation = await WordCountGrader().grade(
        RESULT, case({"word_count": {"eq": 6, "mode": "wat"}})
    )
    assert evaluation.score == 5
