"""Reference :class:`PromptOptimizer` implementation (Task 09).

The optimization loop asks a :class:`PromptOptimizer` to propose a better prompt
given the current :class:`OptimizationContext` (goal, current prompt, measured
strengths/weaknesses, average score, reasoning, and a system prompt).

:class:`LLMOptimizer` composes that context into a structured user prompt, calls
the *active* :class:`~app.core.interfaces.LLMRunner` (``ACTIVE_LLM_RUNNER``) with
the context's ``system_prompt`` (falling back to
``Settings.OPTIMIZER_SYSTEM_PROMPT``), and returns the model's response text as
the improved :class:`Prompt`.

It registers itself on import under both ``("optimizer", "claude_code")`` (the
default ``ACTIVE_OPTIMIZER``) and ``("optimizer", "default")`` so that resolution
via :func:`app.core.registry.get_prompt_optimizer` succeeds out of the box. The runner
is resolved lazily so the active LLM backend stays fully pluggable.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.core.interfaces import PromptOptimizer
from app.core.registry import get_llm_runner, register
from app.models import OptimizationContext, Prompt

__all__ = ["LLMOptimizer"]

logger = logging.getLogger(__name__)


class LLMOptimizer(PromptOptimizer):
    """LLM-backed optimizer that proposes a new prompt from optimizer context."""

    async def optimize(self, ctx: OptimizationContext) -> Prompt:
        """Propose an improved prompt for ``ctx`` via the active LLM runner.

        :param ctx: The current optimization context (goal, current prompt,
            strengths, weaknesses, average score, reasoning, system prompt).
        :returns: A :class:`Prompt` holding the improved prompt text.
        :raises Exception: Propagates any error from the active LLM runner so the
            optimizer can mark the run failed and persist partial results.
        """

        system_prompt = ctx.system_prompt or get_settings().OPTIMIZER_SYSTEM_PROMPT
        user_prompt = self._compose_user_prompt(ctx)

        runner = get_llm_runner()
        raw = await runner.run(system_prompt, user_prompt)
        text = (raw or "").strip()
        if not text:
            # Never propose an empty prompt; keep the loop progressing safely.
            text = ctx.current_prompt
        return Prompt(text=text)

    @staticmethod
    def _compose_user_prompt(ctx: OptimizationContext) -> str:
        """Render the improvement context into a single structured user prompt."""

        strengths = "\n".join(f"- {item}" for item in ctx.strengths) or "- (none)"
        weaknesses = "\n".join(f"- {item}" for item in ctx.weaknesses) or "- (none)"
        score = "n/a" if ctx.avg_score is None else f"{ctx.avg_score:.2f}/10"
        reasoning = ctx.reasoning.strip() or "(none)"

        return (
            f"Goal:\n{ctx.goal}\n\n"
            f"Current prompt:\n{ctx.current_prompt}\n\n"
            f"Current average score: {score}\n\n"
            f"Measured strengths:\n{strengths}\n\n"
            f"Measured weaknesses:\n{weaknesses}\n\n"
            f"Reasoning behind the current evaluation:\n{reasoning}\n\n"
            "Rewrite the prompt so it better satisfies the goal across all test "
            "cases, directly addressing the weaknesses while preserving the "
            "strengths. Return ONLY the improved prompt text."
        )


# Register under the default ACTIVE_OPTIMIZER name ("claude_code") and a generic
# "default" alias so resolution succeeds regardless of which is configured.
register("optimizer", "claude_code", LLMOptimizer)
register("optimizer", "default", LLMOptimizer)
