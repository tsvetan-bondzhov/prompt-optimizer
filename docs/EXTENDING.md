# Extending the Prompt Optimizer

Every pluggable seam follows the same three-step pattern:

1. Implement the ABC from `app/core/interfaces.py`.
2. Register it under a name: `register("<category>", "<name>", Factory)`
   (a class works as a factory; `register` lives in `app/core/registry.py`).
   Do it at import time in your module and make sure the module is imported
   from `app/core/bootstrap.py::register_builtins()` (or from
   `app/implementations/__init__.py`, which the bootstrap imports).
3. Point the matching `ACTIVE_*` setting at your name (env var or `.env`).

Registry categories → settings:

| Category | ABC / protocol | Setting |
|----------|----------------|---------|
| `executor` | `PromptExecutor` | `ACTIVE_EXECUTOR` |
| `evaluation_prepare` | `prepare_evaluation()` factory | `ACTIVE_EXECUTOR` (paired) |
| `improver` | `PromptImprover` | `ACTIVE_IMPROVER` |
| `summarizer` | `Summarizer` | `ACTIVE_SUMMARIZER` |
| `llm_runner` | `LLMRunner` | `ACTIVE_LLM_RUNNER` |
| `aggregator` | `Aggregator` (callable) | — (default: mean) |

> The evaluation-steps factory is resolved with the **executor's** name because
> the executor and its evaluation steps form a matched, user-supplied pair.

## 1. Implement a `PromptExecutor`

The executor defines what "running the prompt" means — an LLM call, a tool
invocation, an HTTP request, anything that turns `(prompt, test_case)` into
output text.

```python
# app/implementations/executor.py (or your own module)
from app.core.interfaces import PromptExecutor
from app.core.registry import register
from app.models import Prompt, PromptResult, TestCase


class MyExecutor(PromptExecutor):
    async def execute(self, prompt: Prompt, test_case: TestCase) -> PromptResult:
        user_input = test_case.data.get("input", "")
        output = await my_backend_call(prompt.text, user_input)
        return PromptResult(text=output)


register("executor", "mine", MyExecutor)
```

Activate with `ACTIVE_EXECUTOR=mine`.

## 2. Implement `EvaluationStep`s and `prepare_evaluation()`

Evaluation steps score a `PromptResult` against a test case's
`evaluation_criteria`. **There is no built-in LLM call** — the scoring logic is
entirely yours (deterministic checks, an LLM judge you wire yourself, etc.).
Each step must return a validated `PromptEvaluation`: 1–3 strengths, 1–3
weaknesses, non-empty reasoning, integer score 1–10.

```python
from app.core.interfaces import EvaluationStep
from app.core.registry import register
from app.models import PromptEvaluation, PromptResult, TestCase


class ContainsAnswerStep(EvaluationStep):
    name = "contains-answer"

    async def evaluate(
        self, result: PromptResult, test_case: TestCase
    ) -> PromptEvaluation:
        expected = test_case.evaluation_criteria.get("expected", "")
        hit = expected.lower() in result.text.lower()
        return PromptEvaluation(
            strengths=["contains the expected answer" if hit else "produced output"],
            weaknesses=["nothing notable" if hit else "expected answer missing"],
            reasoning=f"Checked for {expected!r} in the result.",
            score=9 if hit else 3,
            step_name=self.name,
        )


def prepare_evaluation() -> list[EvaluationStep]:
    # Ordered — steps run sequentially per evaluation point.
    return [ContainsAnswerStep()]


register("evaluation_prepare", "mine", prepare_evaluation)
```

Reference examples ship in `app/implementations/evaluation_steps.py` and
`app/implementations/prepare.py` (registered as `default`).

## 3. Implement a `PromptImprover` or `Summarizer`

Both default implementations delegate to the active `LLMRunner`, so usually you
customize the *prompting*, not the transport:

```python
from app.core.interfaces import PromptImprover
from app.core.registry import get_llm_runner, register
from app.models import ImprovementContext, Prompt


class MyImprover(PromptImprover):
    async def improve(self, ctx: ImprovementContext) -> Prompt:
        runner = get_llm_runner()
        text = await runner.run(
            ctx.system_prompt or "You improve prompts.",
            f"Goal: {ctx.goal}\nCurrent prompt:\n{ctx.current_prompt}\n"
            f"Score: {ctx.avg_score}\nWeaknesses: {ctx.weaknesses}",
        )
        return Prompt(text=text.strip())


register("improver", "mine", MyImprover)
```

Activate with `ACTIVE_IMPROVER=mine`. Summarizers are analogous
(`Summarizer.summarize(list[PromptEvaluation]) -> EvaluationSummary`); see
`app/implementations/summarizer.py` for the LLM-backed `default` and the
deterministic `frequency` fallback.

### The improver system prompt

The default system prompt lives in `app/config.py` as
`DEFAULT_IMPROVER_SYSTEM_PROMPT` — edit the constant, or override it per
deployment with the `IMPROVER_SYSTEM_PROMPT` environment variable.

## 4. Add a new `LLMRunner` (swap away from Claude Code)

The optimizer/summarizer talk to LLMs only through this one-method interface,
so switching from Claude Code headless to Cursor, Copilot, or the Anthropic API
means implementing one class:

```python
from app.core.registry import register
from app.llm.base import LLMRunner, LLMRunnerError


class AnthropicAPIRunner(LLMRunner):
    async def run(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await client.messages.create(   # anthropic AsyncAnthropic
                model="claude-sonnet-5",
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as exc:
            raise LLMRunnerError(f"Anthropic API call failed: {exc}") from exc


register("llm_runner", "anthropic_api", AnthropicAPIRunner)
```

Activate with `ACTIVE_LLM_RUNNER=anthropic_api`. Raise `LLMRunnerError` on
failure so runs are marked `failed` with the error preserved.

Built-in runners: `claude_code` (headless `claude -p` subprocess, path via
`CLAUDE_CLI_PATH`) and `fake` (deterministic echo, offline).

## 5. Custom aggregation

The per-point score defaults to the mean of step scores. Register a callable
under `("aggregator", "default")` to change the strategy:

```python
register("aggregator", "default", lambda: lambda evals: min(e.score for e in evals))
```

## Testing your implementations

Use the fixtures in `tests/conftest.py` as a template: a fresh
`mongomock-motor` database per test, and `register(...)` overwrites to shadow
the active names with your implementation. The whole suite runs with
`pytest` — no network or LLM access required.
