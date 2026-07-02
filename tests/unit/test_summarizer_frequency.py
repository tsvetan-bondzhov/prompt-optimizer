"""Unit tests: deterministic frequency summarizer fallback (Task 15)."""

from __future__ import annotations

from app.implementations.summarizer import DEFAULT_TOP_K, FrequencySummarizer
from app.models import PromptEvaluation


def _evaluation(strengths, weaknesses, score=5, reasoning="r"):
    return PromptEvaluation(
        strengths=strengths, weaknesses=weaknesses, reasoning=reasoning, score=score
    )


async def test_frequency_summarizer_ranks_by_frequency():
    evaluations = [
        _evaluation(["clear", "concise"], ["verbose"]),
        _evaluation(["clear"], ["verbose", "vague"]),
        _evaluation(["clear", "detailed"], ["vague"]),
    ]
    summary = await FrequencySummarizer().summarize(evaluations)
    assert summary.strengths[0] == "clear"  # most frequent first
    assert set(summary.weaknesses) >= {"verbose", "vague"}
    assert summary.reasoning


async def test_frequency_summarizer_bounded_output():
    evaluations = [
        _evaluation([f"s{i}", f"s{i+1}"], [f"w{i}"]) for i in range(0, 10, 2)
    ]
    summary = await FrequencySummarizer().summarize(evaluations)
    assert len(summary.strengths) <= DEFAULT_TOP_K
    assert len(summary.weaknesses) <= DEFAULT_TOP_K


async def test_frequency_summarizer_empty_input():
    summary = await FrequencySummarizer().summarize([])
    assert summary.strengths == []
    assert summary.weaknesses == []
