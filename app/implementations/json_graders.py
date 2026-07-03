"""JSON-oriented :class:`Grader` implementations.

Two steps for prompts whose output is expected to be JSON:

* :class:`JsonSchemaValidationGrader` — parses ``result.text`` as JSON and
  validates it against a JSON Schema read from
  ``test_case.evaluation_criteria["json_schema"]``.
* :class:`JsonExpectedMatchGrader` — parses ``result.text`` as JSON and compares
  it to an expected JSON document (object or array) read from
  ``test_case.evaluation_criteria["expected_json"]``. Objects are traversed in
  both directions (unexpected output fields are mismatches), arrays are
  compared element-wise, and a path is ignored only when it is null/missing on
  both sides. The score is the percentage of compared fields that matched.

Use them by selecting their names in a test case's ``grader_names``
(``json_schema`` / ``json_expected_match``).

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
from app.core.interfaces import Grader
from app.core.registry import register
from app.implementations.graders import clamp_score, trim
from app.models import PromptEvaluation, PromptResult, TestCase

__all__ = ["JsonSchemaValidationGrader", "JsonExpectedMatchGrader"]

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


class _JsonGraderBase(Grader):
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
            grader_name=self.name,
        )


class JsonSchemaValidationGrader(_JsonGraderBase):
    """Validate the JSON output against a schema from the evaluation criteria.

    The schema is read from ``test_case.evaluation_criteria["json_schema"]``
    (or legacy ``"schema"``). Scoring: valid output scores ``10``; output that
    is not parseable as pure JSON (including Markdown-fenced output unless
    fence tolerance is enabled) scores ``1``; schema violations subtract 3
    points each from 10 (floored at 1). When no schema is configured the step
    returns a neutral ``5``, documenting that nothing could be checked.
    """

    name = "json_schema"

    def _schema(
        self, test_case: TestCase, entry_index: int
    ) -> Optional[dict[str, Any]]:
        criteria: dict[str, Any] = self.criteria_for(test_case, entry_index)
        schema = criteria.get("json_schema", criteria.get("schema"))
        return schema if isinstance(schema, dict) else None

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        schema = self._schema(test_case, entry_index)
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
                grader_name=self.name,
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
                grader_name=self.name,
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
            grader_name=self.name,
        )


class JsonExpectedMatchGrader(_JsonGraderBase):
    """Compare the JSON output to an expected JSON document.

    The expected document — a JSON object **or** array — is read from
    ``test_case.evaluation_criteria["expected_json"]`` (or legacy
    ``"expected"``); the output's top-level type must match it. Objects are
    traversed key-by-key in **both** directions,
    arrays element-wise by index, and scalars compared by equality. Each
    compared path falls into one of three buckets:

    * **ignored** — null/missing on **both** sides (the expectation says
      "don't care" and the output agrees);
    * **matched** — present on both sides with an equal value;
    * **mismatched** — unequal value; missing/``null`` in the output while
      the expected value is non-null; a value in the output where ``null``
      was expected; or a field present in the output that does not exist in
      the expected object.

    Score: the percentage of compared (non-ignored) fields that matched,
    mapped linearly onto ``[1, 10]``. Unparseable output scores ``1``; when
    nothing is comparable (all paths null/missing on both sides) the step
    returns a neutral ``5``.
    """

    name = "json_expected_match"

    def _expected(
        self, test_case: TestCase, entry_index: int
    ) -> Optional[dict[str, Any] | list[Any]]:
        criteria: dict[str, Any] = self.criteria_for(test_case, entry_index)
        expected = criteria.get("expected_json", criteria.get("expected"))
        return expected if isinstance(expected, (dict, list)) else None

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        expected = self._expected(test_case, entry_index)
        if expected is None:
            return PromptEvaluation(
                strengths=["Output produced for the test case"],
                weaknesses=["No 'expected_json' configured in evaluation_criteria"],
                reasoning=(
                    "No expected JSON object or array found in "
                    "test_case.evaluation_criteria, so this step cannot compare "
                    "the output; returning a neutral score."
                ),
                score=5,
                grader_name=self.name,
            )

        parsed, parse_error = self._parse(result)
        if parse_error is not None:
            return self._parse_failure(result, parse_error)
        expected_kind = "object" if isinstance(expected, dict) else "array"
        if not isinstance(parsed, type(expected)):
            return PromptEvaluation(
                strengths=["Output is valid JSON"],
                weaknesses=[
                    f"Output is not a JSON {expected_kind}, cannot compare fields"
                ],
                reasoning=(
                    f"The expected JSON is an {expected_kind}, so the output "
                    f"must be a JSON {expected_kind} at the top level; got "
                    f"{type(parsed).__name__}."
                ),
                score=1,
                grader_name=self.name,
            )

        matched: list[str] = []
        ignored: list[str] = []
        mismatched: list[str] = []
        self._compare(expected, parsed, "$", matched, ignored, mismatched)

        compared = len(matched) + len(mismatched)
        if compared == 0:
            return PromptEvaluation(
                strengths=[f"Output is a valid JSON {expected_kind}"],
                weaknesses=[
                    "No fields were comparable "
                    "(all null/missing on both sides)"
                ],
                reasoning=(
                    f"All {len(ignored)} field(s) are null/missing in both the "
                    "expected object and the output, so nothing could be "
                    "verified — neutral score."
                ),
                score=5,
                grader_name=self.name,
            )

        ratio = len(matched) / compared
        score = clamp_score(1 + ratio * 9)  # map [0, 1] -> [1, 10]

        strengths = trim(
            [f"Field {path} matches the expected value" for path in matched]
        ) or [f"Output is a valid JSON {expected_kind}"]
        weaknesses = trim(
            [f"Field {message}" for message in mismatched]
        ) or ["All compared fields match the expected values"]

        reasoning = (
            f"Matched {len(matched)}/{compared} compared field(s) "
            f"({ratio:.0%}); {len(ignored)} field(s) ignored (null/missing on "
            "both sides). Score scaled linearly onto [1, 10]."
        )

        return PromptEvaluation(
            strengths=strengths,
            weaknesses=weaknesses,
            reasoning=reasoning,
            score=score,
            grader_name=self.name,
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
        """Recursively bucket fields as matched/ignored/mismatched.

        Either side may be the ``_MISSING`` sentinel (key absent on that
        side). A path is ignored only when **both** sides are null/missing.
        Objects are traversed key-by-key in both directions (keys present in
        the output but absent from the expected object are mismatches);
        arrays are compared element-wise by index. ``mismatched`` entries are
        human-readable messages that include the path.
        """

        expected_empty = expected is None or expected is _MISSING
        actual_empty = actual is None or actual is _MISSING
        if expected_empty or actual_empty:
            if expected_empty and actual_empty:
                ignored.append(path)
            elif expected_empty and expected is _MISSING:
                mismatched.append(
                    f"{path}: unexpected field not present in the expected JSON"
                )
            elif expected_empty:
                mismatched.append(
                    f"{path}: expected null but the output has a value"
                )
            else:
                mismatched.append(f"{path}: missing or null in the output")
            return

        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                mismatched.append(
                    f"{path}: expected an object, got {type(actual).__name__}"
                )
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
            for key, actual_value in actual.items():
                if key not in expected:
                    self._compare(
                        _MISSING,
                        actual_value,
                        f"{path}.{key}",
                        matched,
                        ignored,
                        mismatched,
                    )
            return

        if isinstance(expected, list):
            if not isinstance(actual, list):
                mismatched.append(
                    f"{path}: expected an array, got {type(actual).__name__}"
                )
                return
            for index in range(max(len(expected), len(actual))):
                self._compare(
                    expected[index] if index < len(expected) else _MISSING,
                    actual[index] if index < len(actual) else _MISSING,
                    f"{path}[{index}]",
                    matched,
                    ignored,
                    mismatched,
                )
            return

        # Scalars are leaves compared by equality.
        if expected == actual:
            matched.append(path)
        else:
            mismatched.append(f"{path}: value does not match the expected value")


# Register the JSON graders by name; test cases select graders through
# ``TestCase.grader_names``.
register("grader", JsonSchemaValidationGrader.name, JsonSchemaValidationGrader)
register("grader", JsonExpectedMatchGrader.name, JsonExpectedMatchGrader)
