"""Ollama-backed :class:`PromptExecutor` for a locally served Mistral model.

The prompt is treated as an ST-extension-style template: ``{placeholder}``
tokens are replaced with the matching values from the data entry (matched
by field name), and escaped curly brackets (``\\{`` / ``\\}``) are unescaped to
literal braces. The rendered prompt is then sent to Ollama's ``/api/generate``
endpoint (non-streaming) and the model's response text is returned.

Configuration (see :class:`app.config.Settings` / ``.env``):

- ``OLLAMA_BASE_URL`` — base URL of the Ollama server (default
  ``http://localhost:11434``).
- ``OLLAMA_MODEL`` — model name passed to Ollama (default ``mistral``).
- ``OLLAMA_TIMEOUT_SECONDS`` — request timeout (default ``120``).

It registers itself under ``("executor", "ollama_mistral")`` on import.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings
from app.core.interfaces import PromptExecutor
from app.core.registry import register
from app.models import PromptText, PromptResult, TestCase

__all__ = ["OllamaMistralExecutor", "OllamaExecutorError", "render_prompt_template"]

# Matches either an escaped brace (``\{`` or ``\}``) or a ``{placeholder}``
# token whose name is a valid identifier. Escapes are matched first so an
# escaped brace never opens or closes a placeholder.
_TEMPLATE_TOKEN_RE = re.compile(r"\\([{}])|\{([A-Za-z_][A-Za-z0-9_]*)\}")


class OllamaExecutorError(Exception):
    """Raised when the Ollama HTTP call fails or returns an unusable payload."""


def render_prompt_template(template: str, data: dict[str, Any]) -> str:
    """Render an ST-extension-style template against a test case's ``data``.

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


class OllamaMistralExecutor(PromptExecutor):
    """Executor that renders the prompt template and runs it via local Ollama."""

    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict[str, Any],
    ) -> PromptResult:
        """Render ``prompt`` with the data ``entry`` and generate via Ollama."""

        settings = get_settings()
        rendered = render_prompt_template(prompt.text, entry or {})
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": rendered,
            "stream": False,
        }
        url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"

        try:
            async with httpx.AsyncClient(
                timeout=settings.OLLAMA_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise OllamaExecutorError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise OllamaExecutorError(
                f"Ollama returned a non-JSON response: {exc}"
            ) from exc

        output_text = body.get("response")
        if not isinstance(output_text, str):
            raise OllamaExecutorError(
                "Ollama response is missing the 'response' text field."
            )
        return PromptResult(text=output_text)


# Register the executor and pair it with the default evaluation steps so
# ``ACTIVE_EXECUTOR=ollama_mistral`` resolves both seams.
register("executor", "ollama_mistral", OllamaMistralExecutor)
