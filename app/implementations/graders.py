"""Reference :class:`Grader` implementations (Task 07).

These are **copy-paste templates** for the user-supplied scoring logic. Per the
design decision, graders ship **no built-in LLM call** — each step
derives a structured :class:`PromptEvaluation` from ``result.text`` and
``test_case.evaluation_criteria`` using deterministic/heuristic logic.

Two reference steps are provided:

* :class:`KeywordCoverageGrader` — scores how many expected keywords (read from
  ``test_case.evaluation_criteria``) appear in the output.
* :class:`ResponseQualityGrader` — a content-agnostic heuristic on the shape of
  the output (non-empty, length within an optional band).

Replace the marked ``# >>> USER`` regions with your own scoring (an LLM-judge
call, regex/JSON assertions, embedding similarity, etc.). Whatever you do, the
step MUST return a valid :class:`PromptEvaluation`:

* ``score``: an integer in ``[1, 10]``
* ``strengths`` / ``weaknesses``: up to 3 non-empty items each (empty is
  fine — only report entries that carry information)
* ``reasoning``: a non-empty string
* ``grader_name``: set to the step's ``name`` for traceability
"""

from __future__ import annotations

from typing import Any

from app.core.interfaces import Grader
from app.core.registry import register
from app.models import PromptEvaluation, PromptResult, TestCase

__all__ = [
    "KeywordCoverageGrader",
    "ResponseQualityGrader",
    "clamp_score",
    "trim",
]


def clamp_score(value: float) -> int:
    """Round ``value`` and clamp it into the valid ``[1, 10]`` score range."""

    return max(1, min(10, round(value)))


def trim(items: list[str], limit: int = 3) -> list[str]:
    """Keep at most ``limit`` non-empty, stripped items (PromptEvaluation caps at 3)."""

    cleaned = [item.strip() for item in items if item and item.strip()]
    return cleaned[:limit]


class KeywordCoverageGrader(Grader):
    """Score the fraction of expected keywords present in the output.

    Expected keywords are read from ``test_case.evaluation_criteria`` under the
    ``"keywords"`` (or legacy ``"expected_keywords"``) key. When no keywords are
    configured the step returns a neutral score, documenting that there was
    nothing to check.
    """

    name = "keyword_coverage"
    display_name = "Keyword coverage"
    description = (
        "Checks which expected keywords appear in the output and scores the "
        "coverage ratio linearly onto 1-10. Without configured keywords the "
        "grader returns a neutral 5."
    )
    criteria_info = [
        {
            "key": "keywords",
            "description": "List of keywords expected to appear in the output "
            "(case-insensitive). Legacy alias: 'expected_keywords'.",
        },
    ]
    criteria_sample = {"keywords": ["refund", "14 days", "support@example.com"]}

    def _expected_keywords(
        self, test_case: TestCase, entry_index: int
    ) -> list[str]:
        criteria: dict[str, Any] = self.criteria_for(test_case, entry_index)
        raw = criteria.get("keywords", criteria.get("expected_keywords", []))
        if isinstance(raw, str):
            raw = [raw]
        return [str(k).strip() for k in raw if str(k).strip()]

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        """Derive a keyword-coverage evaluation from ``result`` and ``test_case``."""

        # >>> USER: this is the heuristic you would replace with your own scoring.
        keywords = self._expected_keywords(test_case, entry_index)
        text_lower = result.text.lower()

        if not keywords:
            return PromptEvaluation(
                weaknesses=["No expected keywords configured to verify against"],
                reasoning=(
                    "No keywords found in test_case.evaluation_criteria, so this "
                    "step cannot measure coverage; returning a neutral score."
                ),
                score=5,
                grader_name=self.name,
            )

        present = [k for k in keywords if k.lower() in text_lower]
        missing = [k for k in keywords if k.lower() not in text_lower]
        coverage = len(present) / len(keywords)
        score = clamp_score(1 + coverage * 9)  # map [0, 1] -> [1, 10]

        strengths = trim([f"Contains expected keyword: {k!r}" for k in present])
        weaknesses = trim([f"Missing expected keyword: {k!r}" for k in missing])

        reasoning = (
            f"Matched {len(present)}/{len(keywords)} expected keywords "
            f"(coverage={coverage:.0%}); score scaled linearly onto [1, 10]."
        )

        return PromptEvaluation(
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
            score=score,
            grader_name=self.name,
        )


class ResponseQualityGrader(Grader):
    """Content-agnostic heuristic on the shape of the output.

    Rewards a non-empty response and (optionally) one whose length falls within
    ``[min_length, max_length]`` bounds read from
    ``test_case.evaluation_criteria``. This is intentionally simple — it shows
    how to combine multiple sub-signals into one score, list of strengths, and
    list of weaknesses.
    """

    name = "response_quality"
    display_name = "Response quality (shape)"
    description = (
        "Content-agnostic heuristic on the shape of the output: rewards a "
        "non-empty response whose length falls within the configured "
        "min/max character bounds."
    )
    criteria_info = [
        {
            "key": "min_length",
            "description": "Minimum output length in characters (default 1).",
        },
        {
            "key": "max_length",
            "description": "Maximum output length in characters (optional).",
        },
    ]
    criteria_sample = {"min_length": 50, "max_length": 800}

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        """Derive a shape/quality evaluation from ``result`` and ``test_case``."""

        # >>> USER: replace this block with your own quality signals.
        criteria: dict[str, Any] = self.criteria_for(test_case, entry_index)
        text = result.text.strip()
        length = len(text)
        min_length = int(criteria.get("min_length", 1))
        max_length_raw = criteria.get("max_length")
        max_length = int(max_length_raw) if max_length_raw is not None else None

        strengths: list[str] = []
        weaknesses: list[str] = []
        score = 5.0

        if length == 0:
            weaknesses.append("Output is empty")
            score = 1.0
        else:
            strengths.append("Output is non-empty")
            score += 2.0

        if length and length >= min_length:
            strengths.append(f"Meets minimum length of {min_length} characters")
            score += 1.0
        elif length:
            weaknesses.append(
                f"Shorter than the configured minimum of {min_length} characters"
            )
            score -= 2.0

        if max_length is not None and length > max_length:
            weaknesses.append(
                f"Exceeds the configured maximum of {max_length} characters"
            )
            score -= 2.0
        elif max_length is not None and length:
            strengths.append(f"Within the maximum length of {max_length} characters")
            score += 1.0

        # Cap at 3 items; empty lists are fine.
        strengths = trim(strengths)
        weaknesses = trim(weaknesses)

        reasoning = (
            f"Heuristic shape check: length={length} chars, "
            f"min_length={min_length}, max_length={max_length}. "
            "Combined sub-signals into a single 1–10 score."
        )

        return PromptEvaluation(
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
            score=clamp_score(score),
            grader_name=self.name,
        )


# Register the reference graders by name; test cases select graders through
# ``TestCase.grader_names``.
register("grader", KeywordCoverageGrader.name, KeywordCoverageGrader)
register("grader", ResponseQualityGrader.name, ResponseQualityGrader)
