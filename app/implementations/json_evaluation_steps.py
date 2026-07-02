"""JSON-oriented :class:`EvaluationStep` implementations.

Two steps for prompts whose output is expected to be JSON:

* :class:`JsonSchemaValidationStep` — parses ``result.text`` as JSON and
  validates it against a JSON Schema read from
  ``test_case.evaluation_criteria["json_schema"]``.
* :class:`JsonExpectedMatchStep` — parses ``result.text`` as JSON and compares
  it to an expected JSON object read from
  ``test_case.evaluation_criteria["expected_json"]``. A field is ignored only
  when its value is ``null`` in the *expected* object; an expected non-null
  field that is missing or ``null`` in the output counts as a mismatch. The
  score is the percentage of compared expected fields that matched.

Use them by returning instances from your ``prepare_evaluation()`` factory::

    def prepare_evaluation() -> list[EvaluationStep]:
        return [JsonSchemaValidationStep(), JsonExpectedMatchStep()]

Markdown code fences: by default the output must be **pure JSON** — a fenced
block (```json ... ```) fails parsing and scores ``1``. Set the
``JSON_EVAL_ALLOW_MARKDOWN=true`` environment variable (or pass
``allow_markdown_fence=True`` to a step's constructor, which takes precedence)
to tolerate fenced output.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from jsonschema import Draft202012Validator

from app.config import get_settings
from app.core.interfaces import EvaluationStep
from app.implementations.evaluation_steps import clamp_score, trim
from app.models import PromptEvaluation, PromptResult, TestCase

__all__ = ["JsonSchemaValidationStep", "JsonExpectedMatchStep"]

_CODE_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*)\n```\s*$", re.DOTALL)

# Sentinel distinguishing "key absent from the output" from an explicit null.
_MISSING = object()


def parse_json_result(
    text: str, *, allow_fence: bool = False
) -> tuple[Optional[Any], Optional[str]]:
    """Parse ``text`` as JSON.

    :param allow_fence: When true, a surrounding Markdown code fence
        (```json ... ```) is unwrapped before parsing. When false the text
        must be pure JSON.
    :returns: ``(value, None)`` on success, ``(None, error message)`` on failure.
    """

    candidate = text.strip()
    if allow_fence:
        fenced = _CODE_FENCE.match(candidate)
        if fenced:
            candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


class _JsonStepBase(EvaluationStep):
    """Shared fence-tolerance resolution for the JSON steps."""

    def __init__(self, *, allow_markdown_fence: Optional[bool] = None) -> None:
        """:param allow_markdown_fence: Override for Markdown-fence tolerance.
        ``None`` (default) defers to the ``JSON_EVAL_ALLOW_MARKDOWN`` setting.
        """

        self._allow_markdown_fence = allow_markdown_fence

    @property
    def allow_fence(self) -> bool:
        if self._allow_markdown_fence is not None:
            return self._allow_markdown_fence
        return get_settings().JSON_EVAL_ALLOW_MARKDOWN

    def _parse(self, result: PromptResult) -> tuple[Optional[Any], Optional[str]]:
        return parse_json_result(result.text, allow_fence=self.allow_fence)

    def _parse_failure(
        self, result: PromptResult, parse_error: str
    ) -> PromptEvaluation:
        fenced = _CODE_FENCE.match(result.text.strip()) is not None
        if fenced and not self.allow_fence:
            weakness = (
                "Output is wrapped in a Markdown code fence instead of pure JSON"
            )
            reasoning = (
                "Pure JSON is expected (JSON_EVAL_ALLOW_MARKDOWN is disabled) "
                f"but the output is Markdown-fenced; parsing failed: {parse_error}"
            )
        else:
            weakness = "Output is not valid JSON"
            reasoning = f"JSON parsing failed: {parse_error}"
        return PromptEvaluation(
            strengths=["Output was produced"],
            weaknesses=[weakness],
            reasoning=reasoning,
            score=1,
            step_name=self.name,
        )


class JsonSchemaValidationStep(_JsonStepBase):
    """Validate the JSON output against a schema from the evaluation criteria.

    The schema is read from ``test_case.evaluation_criteria["json_schema"]``
    (or legacy ``"schema"``). Scoring: valid output scores ``10``; output that
    is not parseable as pure JSON (including Markdown-fenced output unless
    fence tolerance is enabled) scores ``1``; schema violations subtract 3
    points each from 10 (floored at 1). When no schema is configured the step
    returns a neutral ``5``, documenting that nothing could be checked.
    """

    name = "json_schema"

    def _schema(self, test_case: TestCase) -> Optional[dict[str, Any]]:
        criteria: dict[str, Any] = test_case.evaluation_criteria or {}
        schema = criteria.get("json_schema", criteria.get("schema"))
        return schema if isinstance(schema, dict) else None

    async def evaluate(
        self, result: PromptResult, test_case: TestCase
    ) -> PromptEvaluation:
        schema = self._schema(test_case)
        if schema is None:
            return PromptEvaluation(
                strengths=["Output produced for the test case"],
                weaknesses=["No 'json_schema' configured in evaluation_criteria"],
                reasoning=(
                    "No JSON schema found in test_case.evaluation_criteria, so "
                    "this step cannot validate the output; returning a neutral "
                    "score."
                ),
                score=5,
                step_name=self.name,
            )

        parsed, parse_error = self._parse(result)
        if parse_error is not None:
            return self._parse_failure(result, parse_error)

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(parsed), key=lambda e: e.json_path)

        if not errors:
            return PromptEvaluation(
                strengths=["Output is valid JSON", "Output conforms to the schema"],
                weaknesses=["No schema violations detected"],
                reasoning="Parsed the output as JSON and validated it against "
                "the configured schema: no violations.",
                score=10,
                step_name=self.name,
            )

        weaknesses = trim(
            [f"Schema violation at {e.json_path}: {e.message}" for e in errors]
        )
        score = clamp_score(10 - 3 * len(errors))
        return PromptEvaluation(
            strengths=["Output is valid JSON"],
            weaknesses=weaknesses,
            reasoning=(
                f"Output parsed as JSON but failed schema validation with "
                f"{len(errors)} violation(s); scored 10 minus 3 per violation."
            ),
            score=score,
            step_name=self.name,
        )


class JsonExpectedMatchStep(_JsonStepBase):
    """Compare the JSON output to an expected JSON object.

    The expected object is read from
    ``test_case.evaluation_criteria["expected_json"]`` (or legacy
    ``"expected"``). Expected leaf fields (nested objects are traversed;
    scalars and arrays are leaves compared by equality) fall into three
    buckets:

    * **ignored** — the field's value is ``null`` in the *expected* object
      (the expectation itself says "don't care");
    * **matched** — present in the output with an equal value;
    * **mismatched** — unequal value, **or** missing / ``null`` in the output
      while the expected value is non-null.

    Score: the percentage of compared (non-ignored) expected fields that
    matched, mapped linearly onto ``[1, 10]``. Unparseable output scores
    ``1``; when every expected field is ``null`` (nothing comparable) the step
    returns a neutral ``5``.
    """

    name = "json_expected_match"

    def _expected(self, test_case: TestCase) -> Optional[dict[str, Any]]:
        criteria: dict[str, Any] = test_case.evaluation_criteria or {}
        expected = criteria.get("expected_json", criteria.get("expected"))
        return expected if isinstance(expected, dict) else None

    async def evaluate(
        self, result: PromptResult, test_case: TestCase
    ) -> PromptEvaluation:
        expected = self._expected(test_case)
        if expected is None:
            return PromptEvaluation(
                strengths=["Output produced for the test case"],
                weaknesses=["No 'expected_json' configured in evaluation_criteria"],
                reasoning=(
                    "No expected JSON object found in "
                    "test_case.evaluation_criteria, so this step cannot compare "
                    "the output; returning a neutral score."
                ),
                score=5,
                step_name=self.name,
            )

        parsed, parse_error = self._parse(result)
        if parse_error is not None:
            return self._parse_failure(result, parse_error)
        if not isinstance(parsed, dict):
            return PromptEvaluation(
                strengths=["Output is valid JSON"],
                weaknesses=["Output is not a JSON object, cannot compare fields"],
                reasoning=(
                    "Expected-field comparison requires a JSON object at the "
                    f"top level, got {type(parsed).__name__}."
                ),
                score=1,
                step_name=self.name,
            )

        matched: list[str] = []
        ignored: list[str] = []
        mismatched: list[str] = []
        self._compare(expected, parsed, "$", matched, ignored, mismatched)

        compared = len(matched) + len(mismatched)
        if compared == 0:
            return PromptEvaluation(
                strengths=["Output is a valid JSON object"],
                weaknesses=[
                    "No expected fields were comparable "
                    "(all null in the expected object)"
                ],
                reasoning=(
                    f"All {len(ignored)} expected field(s) are null in the "
                    "expected object, so nothing could be verified — neutral "
                    "score."
                ),
                score=5,
                step_name=self.name,
            )

        ratio = len(matched) / compared
        score = clamp_score(1 + ratio * 9)  # map [0, 1] -> [1, 10]

        strengths = trim(
            [f"Field {path} matches the expected value" for path in matched]
        ) or ["Output is a valid JSON object"]
        weaknesses = trim(
            [
                f"Field {path} is missing/null or does not match the expected value"
                for path in mismatched
            ]
        ) or ["All compared fields match the expected values"]

        reasoning = (
            f"Matched {len(matched)}/{compared} compared expected field(s) "
            f"({ratio:.0%}); {len(ignored)} field(s) ignored (null in the "
            "expected object). Score scaled linearly onto [1, 10]."
        )

        return PromptEvaluation(
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
            score=score,
            step_name=self.name,
        )

    def _compare(
        self,
        expected: Any,
        actual: Any,
        path: str,
        matched: list[str],
        ignored: list[str],
        mismatched: list[str],
    ) -> None:
        """Recursively bucket expected leaves as matched/ignored/mismatched.

        ``actual`` may be the ``_MISSING`` sentinel when the key was absent
        from the output. Only a ``null`` in the *expected* object makes a
        field ignorable; a missing/null *actual* against a non-null
        expectation is a mismatch.
        """

        if expected is None:
            ignored.append(path)
            return
        if actual is _MISSING or actual is None:
            mismatched.append(path)
            return

        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                mismatched.append(path)
                return
            for key, expected_value in expected.items():
                self._compare(
                    expected_value,
                    actual.get(key, _MISSING),
                    f"{path}.{key}",
                    matched,
                    ignored,
                    mismatched,
                )
            return

        # Scalars and arrays are leaves compared by equality.
        if expected == actual:
            matched.append(path)
        else:
            mismatched.append(path)
