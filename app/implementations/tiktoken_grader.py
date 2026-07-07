"""Tiktoken token-count :class:`Grader`.

Scores the result based on the number of LLM tokens (counted with
``tiktoken``) read from the evaluation criteria under the ``token_count``
key. The condition object requires two numbers:

* ``target`` — token budget goal; a count **at or below** it scores ``10``;
* ``limit`` — upper bound; a count **above** it scores ``1``.

Between the two the score scales linearly from 10 down to 1. An optional
``mode`` selects what is counted:

* ``response`` (default) — tokens of the execution output;
* ``prompt`` — tokens of the prompt that was actually executed (after any
  template rendering / concatenation);
* ``total`` — prompt + response tokens.

``mode`` may also be given as a separate ``token_count_mode`` criteria key;
the value inside the ``token_count`` object wins. The tiktoken encoding
defaults to ``cl100k_base`` and can be overridden per criteria with
``encoding`` (an encoding name) or ``model`` (a model name resolved through
``tiktoken.encoding_for_model``). Without a usable ``token_count`` condition
the grader returns a neutral ``5``; a tokenizer failure scores ``1`` with the
error recorded.

Registered under ``("grader", "tiktoken")`` on import.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable, Optional

from app.core.interfaces import Grader
from app.core.registry import register
from app.models import PromptEvaluation, PromptResult, TestCase

__all__ = ["TiktokenGrader", "scaled_score"]

_MODES = ("response", "prompt", "total")
_DEFAULT_ENCODING = "cl100k_base"

# (text, encoding_or_model_name) -> token count.
TokenCounter = Callable[[str, str], int]


@lru_cache(maxsize=8)
def _encoding(name: str):
    """Resolve a tiktoken encoding by encoding or model name (cached)."""

    import tiktoken

    try:
        return tiktoken.get_encoding(name)
    except ValueError:
        return tiktoken.encoding_for_model(name)


def _count_tokens(text: str, encoding_name: str) -> int:
    """Number of tiktoken tokens in ``text`` for ``encoding_name``."""

    return len(_encoding(encoding_name).encode(text or ""))


def scaled_score(count: int, target: float, limit: float) -> int:
    """Score 10 at/below ``target``, 1 above ``limit``, linear in between."""

    if count <= target:
        return 10
    if count > limit:
        return 1
    score = round(10 - 9 * (count - target) / (limit - target))
    return max(1, min(10, score))


class TiktokenGrader(Grader):
    """Score the token count against a target / upper-limit budget."""

    name = "tiktoken"
    display_name = "Token count (tiktoken)"
    description = (
        "Counts the LLM tokens of the response (default), the executed "
        "prompt, or both combined with tiktoken. A count at or below the "
        "'target' scores 10, above the 'limit' scores 1, and the score "
        "scales linearly in between."
    )
    criteria_info = [
        {
            "key": "token_count",
            "description": "Condition object with a numeric 'target' (count "
            "<= target scores 10) and 'limit' (count > limit scores 1; "
            "linear in between), an optional 'mode': 'response' (default), "
            "'prompt', or 'total' (prompt + response), and an optional "
            "'encoding' (tiktoken encoding name, default 'cl100k_base') or "
            "'model' (model name the encoding is derived from).",
        },
        {
            "key": "token_count_mode",
            "description": "Alternative place to set the mode; 'mode' inside "
            "'token_count' takes precedence.",
        },
    ]
    criteria_sample = {
        "token_count": {"target": 200, "limit": 800, "mode": "response"}
    }

    def __init__(self, token_counter: Optional[TokenCounter] = None) -> None:
        """:param token_counter: ``(text, encoding_name) -> count`` override —
        injected in tests to avoid tiktoken's encoding download; defaults to
        counting with tiktoken."""

        self._count = token_counter or _count_tokens

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        """Score the configured token budget for one data entry."""

        criteria = self.criteria_for(test_case, entry_index)
        condition = criteria.get("token_count")
        if not isinstance(condition, dict):
            return self._neutral(
                "No 'token_count' condition configured",
                "The tiktoken grader needs a 'token_count' object with "
                "numeric 'target' and 'limit' in the evaluation criteria; "
                "nothing could be checked — neutral score.",
            )

        target = condition.get("target")
        limit = condition.get("limit")
        if not self._is_number(target) or not self._is_number(limit):
            return self._neutral(
                "'token_count' needs numeric 'target' and 'limit'",
                f"Got target={target!r}, limit={limit!r} — both must be "
                "numbers; nothing could be checked, neutral score.",
            )
        if target > limit:
            return self._neutral(
                "'token_count' target exceeds limit",
                f"Got target={target} > limit={limit}; the target must not "
                "exceed the limit — nothing could be checked, neutral score.",
            )

        mode = condition.get("mode") or criteria.get("token_count_mode") or "response"
        if mode not in _MODES:
            return self._neutral(
                f"Unknown token-count mode {mode!r}",
                f"Mode must be one of {', '.join(_MODES)}; got {mode!r} — "
                "nothing could be checked, neutral score.",
            )

        encoding_name = str(
            condition.get("encoding") or condition.get("model") or _DEFAULT_ENCODING
        )
        try:
            response_tokens = self._count(result.text, encoding_name)
            prompt_tokens = self._count(result.prompt_text or "", encoding_name)
        except Exception as exc:  # tokenizer failures must not break the run
            return PromptEvaluation(
                weaknesses=[f"Token counting failed: {exc}"][:3],
                reasoning=(
                    f"tiktoken could not count tokens with encoding "
                    f"{encoding_name!r}: {exc}"
                ),
                score=1,
                grader_name=self.name,
            )
        counted = {
            "response": response_tokens,
            "prompt": prompt_tokens,
            "total": response_tokens + prompt_tokens,
        }[mode]

        score = scaled_score(counted, target, limit)
        budget = f"target {target}, limit {limit} ({encoding_name})"
        if score == 10:
            return PromptEvaluation(
                strengths=[
                    f"{mode.capitalize()} token count {counted} is within the "
                    f"target of {target}"
                ],
                reasoning=(
                    f"Counted {counted} {mode} tokens against {budget}: at or "
                    "below the target."
                ),
                score=score,
                grader_name=self.name,
            )
        if score == 1 and counted > limit:
            return PromptEvaluation(
                weaknesses=[
                    f"{mode.capitalize()} token count {counted} exceeds the "
                    f"limit of {limit}"
                ],
                reasoning=(
                    f"Counted {counted} {mode} tokens against {budget}: above "
                    "the upper limit."
                ),
                score=score,
                grader_name=self.name,
            )
        return PromptEvaluation(
            weaknesses=[
                f"{mode.capitalize()} token count {counted} is over the "
                f"target of {target}"
            ],
            reasoning=(
                f"Counted {counted} {mode} tokens against {budget}: between "
                "target and limit, scored on the linear scale."
            ),
            score=score,
            grader_name=self.name,
        )

    @staticmethod
    def _is_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _neutral(self, weakness: str, reasoning: str) -> PromptEvaluation:
        return PromptEvaluation(
            weaknesses=[weakness],
            reasoning=reasoning,
            score=5,
            grader_name=self.name,
        )


register("grader", TiktokenGrader.name, TiktokenGrader)
