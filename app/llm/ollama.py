"""Ollama-backed :class:`LLMRunner` for locally served models.

Holds the Ollama-specific transport that used to live in the Ollama executor:
the composed prompt is sent to Ollama's ``/api/generate`` endpoint
(non-streaming) and the model's response text is returned.

Configuration (see :class:`app.config.Settings` / ``.env``):

- ``OLLAMA_BASE_URL`` — base URL of the Ollama server (default
  ``http://localhost:11434``).
- ``OLLAMA_MODEL`` — model name passed to Ollama (default ``mistral``).
- ``OLLAMA_TIMEOUT_SECONDS`` — request timeout (default ``120``).

Registered under ``("llm_runner", "ollama")`` by
:func:`app.core.bootstrap.register_builtins`.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.llm.base import LLMRunner, LLMRunnerError, compose_prompt

__all__ = ["OllamaLLMRunner"]


class OllamaLLMRunner(LLMRunner):
    """Run prompts against a local Ollama server (``/api/generate``)."""

    async def run(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a completion for the composed prompt via Ollama."""

        settings = get_settings()
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": compose_prompt(system_prompt, user_prompt),
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
            raise LLMRunnerError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise LLMRunnerError(
                f"Ollama returned a non-JSON response: {exc}"
            ) from exc

        output_text = body.get("response")
        if not isinstance(output_text, str):
            raise LLMRunnerError(
                "Ollama response is missing the 'response' text field."
            )
        return output_text
