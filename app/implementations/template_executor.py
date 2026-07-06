"""Template-rendering :class:`PromptExecutor` (former ``OllamaMistralExecutor``).

The prompt is treated as an ST-extension-style template: ``{placeholder}``
tokens are replaced with the matching values from the data entry (matched by
field name), and escaped curly brackets (``\\{`` / ``\\}``) are unescaped to
literal braces. The rendered prompt is then executed through the LLM runner
selected on the test case (``TestCase.executor_llm_runner``); the executor
itself contains no provider-specific transport (the Ollama specifics live in
:class:`app.llm.ollama.OllamaLLMRunner`).

It registers itself under ``("executor", "template")`` on import.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.interfaces import LLMRunner, PromptExecutor
from app.core.registry import register
from app.models import PromptResult, PromptText, TestCase

__all__ = ["TemplateExecutor", "render_prompt_template"]

# Matches either an escaped brace (``\{`` or ``\}``) or a ``{placeholder}``
# token whose name is a valid identifier. Escapes are matched first so an
# escaped brace never opens or closes a placeholder.
_TEMPLATE_TOKEN_RE = re.compile(r"\\([{}])|\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render_prompt_template(template: str, data: dict[str, Any]) -> str:
    """Render an ST-extension-style template against a data entry.

    ``{name}`` tokens are replaced with ``data["name"]`` (non-string values are
    JSON-encoded); ``\\{`` / ``\\}`` are unescaped to literal braces. Tokens
    with no matching field are left untouched.
    """

    def _substitute(match: re.Match[str]) -> str:
        escaped = match.group(1)
        if escaped is not None:
            return escaped
        key = match.group(2)
        if key not in data:
            return match.group(0)
        value = data[key]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    return _TEMPLATE_TOKEN_RE.sub(_substitute, template)


class TemplateExecutor(PromptExecutor):
    """Render the prompt template with the entry, then delegate to the runner."""

    display_name = "Template"
    description = (
        "Treats the prompt as a template: {placeholder} tokens are replaced "
        "with the matching fields of the data entry (backslash-escaped "
        "braces stay literal; unmatched tokens are left as-is), then the "
        "rendered prompt is sent to the selected LLM runner as a single "
        "prompt."
    )

    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict[str, Any],
        llm_runner: LLMRunner,
    ) -> PromptResult:
        """Render ``prompt`` with ``entry`` and execute it via ``llm_runner``."""

        rendered = render_prompt_template(prompt.text, entry or {})
        output_text = await llm_runner.run("", rendered)
        return PromptResult(text=output_text)


register("executor", "template", TemplateExecutor)
