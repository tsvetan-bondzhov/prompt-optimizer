"""LLM-backed :class:`Grader` ("model grader" / LLM-as-judge).

The grader asks an LLM to judge the prompt result and return a structured
verdict (integer score 1-10, strengths, weaknesses, reasoning). Both the
evaluation prompt and the LLM runner are configured through the test case's
evaluation criteria (per data entry, with dataset fallback):

.. code-block:: json

    {
        "evaluation_prompt": "Judge whether the answer is factually correct.",
        "llm_runner": "ollama"
    }

- ``evaluation_prompt`` (required) — the judging instructions given to the
  model alongside the prompt result.
- ``llm_runner`` (optional) — a registered LLM runner name; the active
  default runner is used when omitted.

The model must answer with a JSON object of the form
``{"score": 1-10, "strengths": [...], "weaknesses": [...], "reasoning": ".."}``;
a Markdown code fence or surrounding prose around the JSON is tolerated. Any
runner failure or unparseable answer scores ``1`` with the error captured in
the evaluation.

Registered under ``("grader", "model_grader")`` on import.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.interfaces import Grader
from app.core.registry import get_llm_runner, register
from app.implementations.graders import clamp_score, trim
from app.models import PromptEvaluation, PromptResult, TestCase

__all__ = ["ModelGrader"]

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a meticulous evaluator of LLM outputs. You will receive "
    "evaluation instructions and the output under evaluation. Judge the "
    "output strictly against the instructions and respond with ONLY a JSON "
    'object of the form {"score": <integer 1-10>, "strengths": ["..."], '
    '"weaknesses": ["..."], "reasoning": "..."}. Provide up to 3 strengths '
    "and up to 3 weaknesses (empty lists are fine when there is nothing "
    "noteworthy), and keep the reasoning to a short paragraph."
)


class ModelGrader(Grader):
    """Grade a prompt result by asking an LLM configured in the criteria."""

    name = "model_grader"
    display_name = "Model grader (LLM-as-judge)"
    description = (
        "Asks an LLM to judge the output against your evaluation "
        "instructions and return a structured verdict (score 1-10, "
        "strengths, weaknesses, reasoning). Judge failures score 1."
    )
    criteria_info = [
        {
            "key": "evaluation_prompt",
            "description": "Required. The judging instructions given to the "
            "model alongside the output under evaluation.",
        },
        {
            "key": "llm_runner",
            "description": "Optional registered LLM runner name used for "
            "judging; the active default runner when omitted.",
        },
        {
            "key": "llm_runner_options",
            "description": "Optional runner-specific options for the judge "
            "(e.g. model, effort, temperature).",
        },
    ]
    criteria_sample = {
        "evaluation_prompt": "Judge whether the answer is factually correct "
        "and directly addresses the question.",
        "llm_runner": "ollama",
    }

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        """Judge ``result`` with the LLM configured in the evaluation criteria."""

        criteria = self.criteria_for(test_case, entry_index)
        evaluation_prompt = str(criteria.get("evaluation_prompt") or "").strip()
        if not evaluation_prompt:
            return PromptEvaluation(
                weaknesses=[
                    "No 'evaluation_prompt' configured in evaluation criteria"
                ],
                reasoning=(
                    "The model grader needs an 'evaluation_prompt' in the "
                    "evaluation criteria; nothing could be judged — returning "
                    "a neutral score."
                ),
                score=5,
                grader_name=self.name,
            )

        runner_name = str(criteria.get("llm_runner") or "").strip() or None
        runner_options = criteria.get("llm_runner_options")
        if not isinstance(runner_options, dict):
            runner_options = None
        user_prompt = (
            f"Evaluation instructions:\n{evaluation_prompt}\n\n"
            f"Output under evaluation:\n{result.text}"
        )

        try:
            runner = get_llm_runner(runner_name)
            raw = await runner.run(SYSTEM_PROMPT, user_prompt, runner_options)
            return self._parse_verdict(raw)
        except Exception as exc:  # noqa: BLE001 - a bad judge must not crash runs
            logger.warning("Model grading failed: %s", exc)
            return PromptEvaluation(
                weaknesses=[f"Model grading failed: {exc}"],
                reasoning=(
                    "The judging LLM call failed or returned an unusable "
                    f"verdict: {exc}"
                ),
                score=1,
                grader_name=self.name,
            )

    def _parse_verdict(self, raw: str) -> PromptEvaluation:
        """Parse the judge's JSON verdict into a :class:`PromptEvaluation`."""

        data = _extract_json_object(raw)

        score = clamp_score(float(data.get("score", 0)))
        strengths = trim(_coerce_str_list(data.get("strengths")))
        weaknesses = trim(_coerce_str_list(data.get("weaknesses")))
        reasoning = data.get("reasoning")
        reasoning = reasoning.strip() if isinstance(reasoning, str) else ""
        if not reasoning:
            reasoning = "The judge returned a verdict without reasoning."

        return PromptEvaluation(
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
            score=score,
            grader_name=self.name,
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

    Tolerates surrounding prose or Markdown code fences by scanning for the
    outermost ``{...}`` span. Raises :class:`ValueError` when no valid JSON
    object can be parsed.
    """

    text = (raw or "").strip()
    if not text:
        raise ValueError("empty judge response")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("no JSON object found in judge response") from None
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("judge response JSON is not an object")
    return parsed


register("grader", ModelGrader.name, ModelGrader)
