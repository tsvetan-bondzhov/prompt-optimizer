"""Reference :class:`PromptExecutor` implementation (Task 07).

This is a **copy-paste template**. The executor is the seam where *running a
prompt* is defined for your use case — an LLM call, a tool invocation, an HTTP
request to your service, etc. The reference version below composes the prompt
with the test case inputs and delegates to the *active* :class:`LLMRunner`
(``ACTIVE_LLM_RUNNER``), which keeps the framework runnable end-to-end out of
the box (use ``FakeLLMRunner`` for fully offline/deterministic runs).

To adapt this to your own target, replace the single clearly-marked line that
produces ``output_text`` (see the ``# >>> USER: replace ...`` marker below).

It registers itself under ``("executor", "default")`` on import so that the
default :class:`~app.config.Settings` (``ACTIVE_EXECUTOR="default"``) resolves
to it.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.interfaces import PromptExecutor
from app.core.registry import get_llm_runner, register
from app.models import Prompt, PromptResult, TestCase

__all__ = ["ReferencePromptExecutor", "render_test_case_input"]


def render_test_case_input(test_case: TestCase) -> str:
    """Render a test case's ``data`` mapping into a single user-prompt string.

    A trivial, readable default: if ``data`` is empty, fall back to the test
    case name; otherwise emit the inputs as pretty JSON. Replace this with
    whatever shape your target expects.
    """

    data: dict[str, Any] = test_case.data or {}
    if not data:
        return test_case.name
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


class ReferencePromptExecutor(PromptExecutor):
    """Example executor that runs ``prompt`` against ``test_case`` via an LLM.

    The reference behavior treats ``prompt.text`` as the system prompt and the
    rendered test-case inputs as the user prompt, then calls the active
    :class:`LLMRunner`. Swap the marked line for your own target invocation.
    """

    async def execute(self, prompt: Prompt, test_case: TestCase) -> PromptResult:
        """Run ``prompt`` against ``test_case`` and return its output."""

        system_prompt = prompt.text
        user_prompt = render_test_case_input(test_case)

        # >>> USER: replace this line with your own target invocation. <<<
        # The reference delegates to the active LLMRunner so the framework runs
        # end-to-end. Your executor might instead call an API, run a tool, etc.
        output_text = await get_llm_runner().run(system_prompt, user_prompt)

        return PromptResult(text=output_text)


# Register the reference executor under the default name on import so that
# ``ACTIVE_EXECUTOR="default"`` resolves to it. ``register`` is idempotent for a
# given (category, name) pair (re-registration overwrites).
register("executor", "default", ReferencePromptExecutor)
