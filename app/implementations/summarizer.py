"""Reference :class:`Summarizer` implementations (Task 10).

Two summarizers condense many per-grader :class:`PromptEvaluation` objects (across
all test cases × executions) into a single compact :class:`EvaluationSummary`
(consolidated strengths, weaknesses, reasoning) used to update optimizer state
and feed the next improvement step.

* :class:`FrequencySummarizer` (registered ``frequency``) — a deterministic,
  offline aggregator. It ranks strengths/weaknesses by frequency, keeps the
  top-K of each, and concatenates/trims the per-grader reasoning. It performs
  **zero external/LLM calls**, making it suitable for tests and offline mode.

* :class:`LLMSummarizer` (registered ``default``) — composes all
  strengths/weaknesses/reasoning + scores into a prompt, calls the *active*
  :class:`LLMRunner` (``ACTIVE_LLM_RUNNER``) to produce a concise structured
  JSON summary, and parses it into an :class:`EvaluationSummary`. On any runner,
  parse, or validation failure it falls back to the deterministic frequency
  aggregation so the loop never stalls.

Both register themselves on import so that the default
:class:`~app.config.Settings` (``ACTIVE_SUMMARIZER="default"``) resolves to the
LLM-backed summarizer, while ``frequency`` is available for offline use.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from app.core.interfaces import Summarizer
from app.core.registry import get_llm_runner, register
from app.models import EvaluationSummary, PromptEvaluation

__all__ = [
    "FrequencySummarizer",
    "LLMSummarizer",
    "DEFAULT_TOP_K",
    "aggregate_by_frequency",
]

logger = logging.getLogger(__name__)

# Default cap on the number of strengths/weaknesses kept in a summary, sized to
# fit comfortably inside the optimizer's context window.
DEFAULT_TOP_K = 3


def _top_k_by_frequency(items: list[str], top_k: int) -> list[str]:
    """Return the ``top_k`` most frequent non-empty items, preserving order.

    Items are compared case-insensitively after stripping, but the original
    (first-seen) casing is preserved in the output. Ties break by first
    appearance so the result is deterministic.
    """

    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    order: dict[str, int] = {}
    for index, raw in enumerate(items):
        cleaned = (raw or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        counts[key] += 1
        if key not in display:
            display[key] = cleaned
            order[key] = index

    # Sort by descending frequency, then by first appearance for stability.
    ranked = sorted(counts, key=lambda key: (-counts[key], order[key]))
    return [display[key] for key in ranked[:top_k]]


def _representative_score(scores: list[int]) -> float:
    """Return the mean of ``scores`` (``0.0`` for an empty list)."""

    return sum(scores) / len(scores) if scores else 0.0


def aggregate_by_frequency(
    evaluations: list[PromptEvaluation], top_k: int = DEFAULT_TOP_K
) -> EvaluationSummary:
    """Deterministically merge ``evaluations`` into one :class:`EvaluationSummary`.

    Strengths and weaknesses are ranked by frequency (top-K each); the reasoning
    is a concise, bounded synthesis describing the aggregation. Performs no
    external calls.
    """

    if top_k < 1:
        top_k = 1

    all_strengths: list[str] = []
    all_weaknesses: list[str] = []
    all_reasoning: list[str] = []
    scores: list[int] = []

    for evaluation in evaluations:
        all_strengths.extend(evaluation.strengths)
        all_weaknesses.extend(evaluation.weaknesses)
        if evaluation.reasoning.strip():
            all_reasoning.append(evaluation.reasoning.strip())
        scores.append(evaluation.score)

    strengths = _top_k_by_frequency(all_strengths, top_k)
    weaknesses = _top_k_by_frequency(all_weaknesses, top_k)

    if evaluations:
        avg = _representative_score(scores)
        reasoning = (
            f"Aggregated {len(evaluations)} evaluation(s) with a representative "
            f"(mean) score of {avg:.2f}/10. Kept the top {len(strengths)} "
            f"strength(s) and top {len(weaknesses)} weakness(es) by frequency."
        )
    else:
        reasoning = "No evaluations were provided to summarize."

    return EvaluationSummary(
        strengths=strengths,
        weaknesses=weaknesses,
        reasoning=reasoning,
    )


class FrequencySummarizer(Summarizer):
    """Deterministic, offline summarizer that aggregates by frequency.

    Ranks strengths/weaknesses across all evaluations by frequency and keeps the
    ``top_k`` of each. Performs **zero external/LLM calls**, so it is ideal for
    tests and offline mode.
    """

    def __init__(self, top_k: int = DEFAULT_TOP_K) -> None:
        """:param top_k: Maximum strengths/weaknesses to keep (>= 1)."""

        self._top_k = max(1, top_k)

    async def summarize(
        self, evaluations: list[PromptEvaluation]
    ) -> EvaluationSummary:
        """Merge ``evaluations`` into one summary by frequency (no I/O)."""

        return aggregate_by_frequency(evaluations, self._top_k)


class LLMSummarizer(Summarizer):
    """LLM-backed summarizer with a deterministic frequency fallback.

    Composes the per-grader strengths/weaknesses/reasoning + scores into a prompt,
    asks the *active* :class:`LLMRunner` for a concise structured JSON summary,
    and parses it into an :class:`EvaluationSummary` bounded by ``top_k``. Any
    runner, parse, or validation failure falls back to
    :func:`aggregate_by_frequency` so the optimization loop never stalls.
    """

    #: Guidance the model receives describing the required JSON output shape.
    SYSTEM_PROMPT = (
        "You are a meticulous prompt-evaluation analyst. You will be given "
        "multiple structured evaluations of a single prompt (each with "
        "strengths, weaknesses, reasoning, and a 1-10 score). Consolidate them "
        "into a single concise summary. Respond with ONLY a JSON object of the "
        'form {"strengths": [..], "weaknesses": [..], "reasoning": ".."}. '
        "Keep the strengths and weaknesses lists to the most important, "
        "deduplicated points and the reasoning to a short paragraph."
    )

    def __init__(self, top_k: int = DEFAULT_TOP_K) -> None:
        """:param top_k: Maximum strengths/weaknesses to keep (>= 1)."""

        self._top_k = max(1, top_k)

    async def summarize(
        self, evaluations: list[PromptEvaluation]
    ) -> EvaluationSummary:
        """Summarize ``evaluations`` via the active LLM, falling back on error."""

        if not evaluations:
            return aggregate_by_frequency(evaluations, self._top_k)

        user_prompt = self._compose_user_prompt(evaluations)

        try:
            runner = get_llm_runner()
            raw = await runner.run(self.SYSTEM_PROMPT, user_prompt)
            return self._parse_summary(raw)
        except Exception as exc:  # noqa: BLE001 - fall back on any failure
            logger.warning(
                "LLM summarization failed (%s); falling back to frequency "
                "aggregation.",
                exc,
            )
            return aggregate_by_frequency(evaluations, self._top_k)

    def _compose_user_prompt(self, evaluations: list[PromptEvaluation]) -> str:
        """Render all evaluations into a single structured user prompt."""

        payload = [
            {
                "grader_name": evaluation.grader_name,
                "score": evaluation.score,
                "strengths": evaluation.strengths,
                "weaknesses": evaluation.weaknesses,
                "reasoning": evaluation.reasoning,
            }
            for evaluation in evaluations
        ]
        body = json.dumps(payload, indent=2, ensure_ascii=False)
        return (
            f"Consolidate the following {len(evaluations)} evaluation(s) into a "
            f"single summary. Keep at most {self._top_k} strengths and {self._top_k} "
            "weaknesses, ordered by importance. Evaluations:\n"
            f"{body}"
        )

    def _parse_summary(self, raw: str) -> EvaluationSummary:
        """Parse the LLM's response text into a bounded :class:`EvaluationSummary`.

        Raises on malformed JSON or invalid structure; callers handle the
        fallback. The strengths/weaknesses are trimmed to ``top_k`` and the
        result is validated through the Pydantic model.
        """

        data = _extract_json_object(raw)

        strengths = _coerce_str_list(data.get("strengths"))[: self._top_k]
        weaknesses = _coerce_str_list(data.get("weaknesses"))[: self._top_k]
        reasoning = data.get("reasoning")
        reasoning = reasoning.strip() if isinstance(reasoning, str) else ""

        return EvaluationSummary(
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
        )


def _coerce_str_list(value: Any) -> list[str]:
    """Coerce ``value`` into a list of non-empty, stripped strings."""

    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Extract and parse the first JSON object found in ``raw``.

    Tolerates surrounding prose or markdown code fences by scanning for the
    outermost ``{...}`` span. Raises :class:`ValueError` when no valid JSON
    object can be parsed.
    """

    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found in LLM response") from None
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON is not an object")
    return parsed


# Register reference summarizers on import so configured names resolve. The
# LLM-backed summarizer is the default; ``frequency`` is the offline fallback.
register("summarizer", "default", LLMSummarizer)
register("summarizer", "frequency", FrequencySummarizer)
