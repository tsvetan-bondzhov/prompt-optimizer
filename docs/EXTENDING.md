# Extending the Prompt Optimizer

Every pluggable seam follows the same three-step pattern:

1. Implement the ABC from `app/core/interfaces.py`.
2. Register it under a name: `register("<category>", "<name>", Factory)`
   (a class works as a factory; `register` lives in `app/core/registry.py`).
   Do it at import time in your module and make sure the module is imported
   from `app/core/bootstrap.py::register_builtins()` (or from
   `app/implementations/__init__.py`, which the bootstrap imports).
3. Select the implementation — most seams are now chosen **per test case /
   per prompt in the UI**; the `ACTIVE_*` settings only provide the defaults.

Registry categories:

| Category | ABC / protocol | Selected by |
|----------|----------------|-------------|
| `executor` | `PromptExecutor` | per test case (`executor_name`); default `ACTIVE_EXECUTOR` |
| `grader` | `Grader` | per test case (`grader_names` checkboxes) |
| `optimizer` | `PromptOptimizer` | `ACTIVE_OPTIMIZER` |
| `summarizer` | `Summarizer` | `ACTIVE_SUMMARIZER` |
| `llm_runner` | `LLMRunner` | per test case (`executor_llm_runner`, `summarizer_llm_runner`) and per prompt (`optimizer_llm_runner`); default `ACTIVE_LLM_RUNNER` |
| `aggregator` | `Aggregator` (callable) | — (default: mean) |

## 1. Implement a `PromptExecutor`

The executor defines what "running the prompt" means. A test case's `data` is
an **array of entries**; the executor is invoked once per entry. Executors do
not talk to a provider directly — they receive the `LLMRunner` selected on the
test case (`executor_llm_runner`) and delegate the actual LLM call to it
(executors that don't need an LLM may ignore it).

```python
# app/implementations/executor.py (or your own module)
from app.core.interfaces import LLMRunner, PromptExecutor
from app.core.registry import register
from app.models import PromptResult, PromptText, TestCase


class MyExecutor(PromptExecutor):
    async def execute(
        self,
        prompt: PromptText,
        test_case: TestCase,
        entry: dict,
        llm_runner: LLMRunner,
    ) -> PromptResult:
        user_input = entry.get("input", "")
        output = await llm_runner.run(prompt.text, user_input)
        return PromptResult(text=output)


register("executor", "mine", MyExecutor)
```

Once registered, `mine` appears as a radio button in the test case form.

Give your implementation UI metadata — `display_name`, `description`,
`criteria_info` (documented criteria keys), and `criteria_sample`
(copy-pasteable snippet) — and the test case form shows the friendly name
with an info popup.

Built-in executors:

- `default` — treats `prompt.text` as the system prompt and the pretty-printed
  entry as the user prompt.
- `template` — renders `{placeholder}` tokens in the prompt from the entry's
  fields (`\{` / `\}` escape literal braces), then sends the rendered prompt
  through the selected runner. (This is the former `OllamaMistralExecutor`;
  the Ollama transport now lives in the `ollama` LLM runner.)
- `no_args` — sends the prompt as-is, ignoring the data entry.
- `concat` — appends the JSON-serialized data entry to the prompt.

## 2. Implement a `Grader`

Graders score a `PromptResult`. They are selected **per test case** via
checkboxes (`TestCase.grader_names`). A grader is invoked once per data entry;
use `self.criteria_for(test_case, entry_index)` to read the evaluation
criteria — it resolves them **per key**: a key present in
`evaluation_criteria_per_entry[entry_index]` wins, and every other key falls
back to the dataset-level `evaluation_criteria`. Different keys can live at
different levels — e.g. `expected_json` typically varies per entry while
`json_schema` is defined once for the whole dataset. Each grader must return a
validated `PromptEvaluation`: up to 3 strengths and up to 3 weaknesses
(empty lists are fine — omit entries that carry no information, e.g. a
weakness saying everything passed), non-empty reasoning, integer score 1–10.

```python
from app.core.interfaces import Grader
from app.core.registry import register
from app.models import PromptEvaluation, PromptResult, TestCase


class ContainsAnswerGrader(Grader):
    name = "contains-answer"

    async def grade(
        self,
        result: PromptResult,
        test_case: TestCase,
        entry_index: int = 0,
    ) -> PromptEvaluation:
        criteria = self.criteria_for(test_case, entry_index)
        expected = criteria.get("expected", "")
        hit = expected.lower() in result.text.lower()
        return PromptEvaluation(
            strengths=["contains the expected answer" if hit else "produced output"],
            weaknesses=["nothing notable" if hit else "expected answer missing"],
            reasoning=f"Checked for {expected!r} in the result.",
            score=9 if hit else 3,
            grader_name=self.name,
        )


register("grader", ContainsAnswerGrader.name, ContainsAnswerGrader)
```

Built-in graders: `keyword_coverage`, `response_quality`
(`app/implementations/graders.py`), `json_schema`, `json_expected_match`
(`app/implementations/json_graders.py`), `word_count`
(`app/implementations/word_count_grader.py` — eq/gt/lt/gte/lte conditions
with a response/prompt/total mode), and `model_grader`
(`app/implementations/model_grader.py`).

### The model grader (LLM-as-judge)

`model_grader` asks an LLM to judge the result. Configure it entirely through
the evaluation criteria (per entry or dataset-level):

```json
{
    "evaluation_prompt": "Judge whether the answer is factually correct.",
    "llm_runner": "ollama"
}
```

The judge must answer with `{"score": 1-10, "strengths": [...],
"weaknesses": [...], "reasoning": "..."}`; failures score 1 and are recorded
in the evaluation.

## 3. Implement a `PromptOptimizer` or `Summarizer`

Both default implementations delegate to an `LLMRunner`, so usually you
customize the *prompting*, not the transport. The optimizer uses the runner
selected on the prompt (`Prompt.optimizer_llm_runner`, exposed through
`OptimizationContext.llm_runner_name`); the summarizer receives the runner
selected on the test case (`summarizer_llm_runner`).

```python
from app.core.interfaces import PromptOptimizer
from app.core.registry import get_llm_runner, register
from app.models import OptimizationContext, PromptText


class MyOptimizer(PromptOptimizer):
    async def optimize(self, ctx: OptimizationContext) -> PromptText:
        runner = get_llm_runner(ctx.llm_runner_name)
        text = await runner.run(
            ctx.system_prompt or "You improve prompts.",
            f"Goal: {ctx.goal}\nCurrent prompt:\n{ctx.current_prompt}\n"
            f"Score: {ctx.avg_score}\nWeaknesses: {ctx.weaknesses}",
        )
        return PromptText(text=text.strip())


register("optimizer", "mine", MyOptimizer)
```

Activate with `ACTIVE_OPTIMIZER=mine`. Summarizers are analogous
(`Summarizer.summarize(list[PromptEvaluation], llm_runner=None) ->
EvaluationSummary`); see `app/implementations/summarizer.py` for the
LLM-backed `default` and the deterministic `frequency` fallback.

### The optimizer system prompt

The default system prompt lives in `app/config.py` as
`DEFAULT_OPTIMIZER_SYSTEM_PROMPT` — edit the constant, or override it per
deployment with the `OPTIMIZER_SYSTEM_PROMPT` environment variable.

## 4. Add a new `LLMRunner`

Executors, the optimizer, the summarizer, and the model grader all talk to
LLMs only through this one-method interface. New runners immediately become
selectable in the test case and prompt forms:

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

Raise `LLMRunnerError` on failure so runs are marked `failed` with the error
preserved.

Runners can declare an `options_schema` (list of
`{"name", "label", "type", "default"}`) — the UI then offers those inputs
wherever the runner is selectable and stores the values with the test case /
prompt; they arrive back through the `options` argument of `run()`. Built-in
schemas: `claude_code` (model, defaulting to `claude-sonnet-4-6`; effort;
temperature — empty values are ignored and map to `--model` / `--effort` /
`--temperature` CLI flags) and `ollama` (model, defaulting to `mistral`;
temperature).

Built-in runners: `claude_code` (headless `claude -p` subprocess, path via
`CLAUDE_CLI_PATH`), `ollama` (local Ollama server via `OLLAMA_*` settings),
and `fake` (deterministic echo, offline).

## 5. Custom aggregation

The per-entry score defaults to the mean of the grader scores (and the point
score to the mean over entries). Register a callable under
`("aggregator", "default")` to change the per-entry strategy:

```python
register("aggregator", "default", lambda: lambda evals: min(e.score for e in evals))
```

## Testing your implementations

Use the fixtures in `tests/conftest.py` as a template: a fresh
`mongomock-motor` database per test, and `register(...)` overwrites to shadow
registered names with fakes (e.g. the `fake` grader). The whole suite runs
with `pytest` — no network or LLM access required.
