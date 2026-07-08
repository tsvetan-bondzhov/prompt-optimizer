"""Unit tests: TiktokenGrader budget scoring and modes."""

from __future__ import annotations

import pytest

from app.implementations.tiktoken_grader import TiktokenGrader, scaled_score
from app.models import PromptResult, TestCase

# The fake counter treats every whitespace-separated word as one token:
# 4 prompt tokens, 6 response tokens.
RESULT = PromptResult(
    text="one two three four five six",
    prompt_text="alpha beta gamma delta",
)


def fake_counter(text: str, encoding_name: str) -> int:
    return len((text or "").split())


def grader() -> TiktokenGrader:
    return TiktokenGrader(token_counter=fake_counter)


def case(criteria: dict) -> TestCase:
    return TestCase(name="tc", grader_names=["tiktoken"], evaluation_criteria=criteria)


@pytest.mark.parametrize(
    ("count", "target", "limit", "expected"),
    [
        (10, 10, 20, 10),  # at target
        (5, 10, 20, 10),  # below target
        (21, 10, 20, 1),  # above limit
        (20, 10, 20, 1),  # at limit -> bottom of the linear scale
        (15, 10, 20, 6),  # midpoint: 10 - 9 * 0.5 = 5.5 -> 6
        (12, 10, 20, 8),
        (18, 10, 20, 3),
        (11, 10, 10, 1),  # target == limit acts as a hard threshold
        (10, 10, 10, 10),
    ],
)
def test_scaled_score(count, target, limit, expected):
    assert scaled_score(count, target, limit) == expected


async def test_score_10_at_or_below_target():
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 6, "limit": 20}})
    )
    assert evaluation.score == 10
    assert evaluation.strengths


async def test_score_1_above_limit():
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 2, "limit": 5}})
    )
    assert evaluation.score == 1
    assert "exceeds the limit" in evaluation.weaknesses[0]


async def test_linear_scale_between_target_and_limit():
    # count 6, target 4, limit 8 -> 10 - 9 * 2/4 = 5.5 -> 6.
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 4, "limit": 8}})
    )
    assert evaluation.score == 6
    assert "over the target" in evaluation.weaknesses[0]


async def test_prompt_mode_counts_executed_prompt():
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 4, "limit": 8, "mode": "prompt"}})
    )
    assert evaluation.score == 10


async def test_total_mode_counts_prompt_plus_response():
    # total 10, target 5, limit 15 -> 10 - 9 * 5/10 = 5.5 -> 6.
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 5, "limit": 15, "mode": "total"}})
    )
    assert evaluation.score == 6


async def test_mode_via_token_count_mode_key():
    evaluation = await grader().grade(
        RESULT,
        case({"token_count": {"target": 4, "limit": 8}, "token_count_mode": "prompt"}),
    )
    assert evaluation.score == 10


async def test_mode_inside_condition_wins():
    evaluation = await grader().grade(
        RESULT,
        case(
            {
                "token_count": {"target": 6, "limit": 8, "mode": "response"},
                "token_count_mode": "prompt",
            }
        ),
    )
    assert evaluation.score == 10


async def test_missing_condition_is_neutral():
    evaluation = await grader().grade(RESULT, case({}))
    assert evaluation.score == 5


async def test_non_numeric_budget_is_neutral():
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": "a", "limit": 5}})
    )
    assert evaluation.score == 5


async def test_target_above_limit_is_neutral():
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 9, "limit": 5}})
    )
    assert evaluation.score == 5


async def test_unknown_mode_is_neutral():
    evaluation = await grader().grade(
        RESULT, case({"token_count": {"target": 4, "limit": 8, "mode": "wat"}})
    )
    assert evaluation.score == 5


async def test_tokenizer_failure_scores_1():
    def broken_counter(text: str, encoding_name: str) -> int:
        raise RuntimeError("no encoding data")

    evaluation = await TiktokenGrader(token_counter=broken_counter).grade(
        RESULT, case({"token_count": {"target": 4, "limit": 8}})
    )
    assert evaluation.score == 1
    assert "Token counting failed" in evaluation.weaknesses[0]
