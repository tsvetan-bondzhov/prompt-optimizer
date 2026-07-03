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
* ``strengths`` / ``weaknesses``: 1–3 non-empty items each
* ``reasoning``: a non-empty string
* ``grader_name``: set to the step's ``name`` for traceability
"""

from __future__ import annotations

from typing import Any

from app.core.interfaces import Grader
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

    def _expected_keywords(self, test_case: TestCase) -> list[str]:
        criteria: dict[str, Any] = test_case.evaluation_criteria or {}
        raw = criteria.get("keywords", criteria.get("expected_keywords", []))
        if isinstance(raw, str):
            raw = [raw]
        return [str(k).strip() for k in raw if str(k).strip()]

    async def grade(
        self, result: PromptResult, test_case: TestCase
    ) -> PromptEvaluation:
        """Derive a keyword-coverage evaluation from ``result`` and ``test_case``."""

        # >>> USER: this is the heuristic you would replace with your own scoring.
        keywords = self._expected_keywords(test_case)
        text_lower = result.text.lower()

        if not keywords:
            return PromptEvaluation(
                strengths=["Output produced for the test case"],
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

        strengths = trim(
            [f"Contains expected keyword: {k!r}" for k in present]
        ) or ["Output was generated and inspected for keyword coverage"]
        weaknesses = trim(
            [f"Missing expected keyword: {k!r}" for k in missing]
        ) or ["All expected keywords were present"]

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

    async def grade(
        self, result: PromptResult, test_case: TestCase
    ) -> PromptEvaluation:
        """Derive a shape/quality evaluation from ``result`` and ``test_case``."""

        # >>> USER: replace this block with your own quality signals.
        criteria: dict[str, Any] = test_case.evaluation_criteria or {}
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

        # Guarantee the 1–3 item / non-empty constraints regardless of branch.
        strengths = trim(strengths) or ["Output was generated and inspected"]
        weaknesses = trim(weaknesses) or ["No structural issues detected"]

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
