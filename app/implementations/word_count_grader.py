"""Word-count :class:`Grader`.

Scores the result based on a word-count condition read from the evaluation
criteria under the ``word_count`` key. The condition object supports the
comparison operators ``eq``, ``gt``, ``lt``, ``gte``, and ``lte`` (combinable,
e.g. ``{"gte": 10, "lte": 20}``) plus an optional ``mode`` selecting what is
counted:

* ``response`` (default) — words in the execution output;
* ``prompt`` — words in the prompt that was actually executed (after any
  template rendering / concatenation);
* ``total`` — prompt + response words.

``mode`` may also be given as a separate ``word_count_mode`` criteria key;
the value inside the ``word_count`` object wins. All configured conditions
must hold for a score of ``10``; otherwise the grader scores ``1``. Without a
``word_count`` condition the grader returns a neutral ``5``.

Registered under ``("grader", "word_count")`` on import.
"""

from __future__ import annotations

from typing import Any

from app.core.interfaces import Grader
from app.core.registry import register
from app.models import PromptEvaluation, PromptResult, TestCase

__all__ = ["WordCountGrader", "count_words"]

_OPERATORS = {
    "eq": lambda count, limit: count == limit,
    "gt": lambda count, limit: count > limit,
    "lt": lambda count, limit: count < limit,
    "gte": lambda count, limit: count >= limit,
    "lte": lambda count, limit: count <= limit,
}

_MODES = ("response", "prompt", "total")


def count_words(text: str) -> int:
    """Number of whitespace-separated words in ``text``."""

    return len((text or "").split())


class WordCountGrader(Grader):
    """Score the result against a configurable word-count condition."""

    name = "word_count"
    display_name = "Word count"
    description = (
        "Counts the words of the response (default), the executed prompt, or "
        "both combined, and checks the count against the configured "
        "comparison operators. All conditions met scores 10, otherwise 1."
    )
    criteria_info = [
        {
            "key": "word_count",
            "description": "Condition object with any of the operators 'eq', "
            "'gt', 'lt', 'gte', 'lte' (combinable) and an optional 'mode': "
            "'response' (default), 'prompt', or 'total' (prompt + response).",
        },
        {
            "key": "word_count_mode",
            "description": "Alternative place to set the mode; 'mode' inside "
            "'word_count' takes precedence.",
        },
    ]
    criteria_sample = {"word_count": {"gte": 30, "lte": 120, "mode": "response"}}

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        """Check the configured word-count condition for one data entry."""

        criteria = self.criteria_for(test_case, entry_index)
        condition = criteria.get("word_count")
        if not isinstance(condition, dict) or not (
            set(condition) & set(_OPERATORS)
        ):
            return PromptEvaluation(
                weaknesses=["No 'word_count' condition configured"],
                reasoning=(
                    "The word-count grader needs a 'word_count' object with "
                    "at least one of eq/gt/lt/gte/lte in the evaluation "
                    "criteria; nothing could be checked — neutral score."
                ),
                score=5,
                grader_name=self.name,
            )

        mode = condition.get("mode") or criteria.get("word_count_mode") or "response"
        if mode not in _MODES:
            return PromptEvaluation(
                weaknesses=[f"Unknown word-count mode {mode!r}"],
                reasoning=(
                    f"Mode must be one of {', '.join(_MODES)}; got {mode!r} — "
                    "nothing could be checked, neutral score."
                ),
                score=5,
                grader_name=self.name,
            )

        response_words = count_words(result.text)
        prompt_words = count_words(result.prompt_text or "")
        counted = {
            "response": response_words,
            "prompt": prompt_words,
            "total": response_words + prompt_words,
        }[mode]

        failed: list[str] = []
        checked: list[str] = []
        for op, comparator in _OPERATORS.items():
            if op not in condition:
                continue
            limit = condition[op]
            checked.append(f"{op} {limit}")
            if not isinstance(limit, (int, float)) or isinstance(limit, bool):
                failed.append(f"'{op}' limit is not a number: {limit!r}")
            elif not comparator(counted, limit):
                failed.append(f"{mode} word count {counted} fails '{op} {limit}'")

        if failed:
            return PromptEvaluation(
                weaknesses=failed[:3],
                reasoning=(
                    f"Checked the {mode} word count ({counted}) against: "
                    f"{', '.join(checked)}. At least one condition failed."
                ),
                score=1,
                grader_name=self.name,
            )

        return PromptEvaluation(
            strengths=[
                f"{mode.capitalize()} word count {counted} satisfies "
                f"{', '.join(checked)}"
            ],
            reasoning=(
                f"Checked the {mode} word count ({counted}) against: "
                f"{', '.join(checked)}. All conditions hold."
            ),
            score=10,
            grader_name=self.name,
        )


register("grader", WordCountGrader.name, WordCountGrader)
