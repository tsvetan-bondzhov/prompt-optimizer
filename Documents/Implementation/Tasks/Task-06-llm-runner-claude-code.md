# Task 06 — LLM Runner + Claude Code Headless

**Depends on:** 05
**Milestone:** Engine

## Objective
Provide a pluggable `LLMRunner` abstraction and a default implementation that
invokes **Claude Code in headless mode (`claude -p`)**, designed to be swapped
for Cursor / Copilot / Anthropic API later.

## Steps
1. `app/llm/base.py`: re-export / define `LLMRunner` ABC (`async run(system_prompt, user_prompt) -> str`).
2. `app/llm/claude_code.py` — `ClaudeCodeRunner(LLMRunner)`:
   - Invoke the CLI via `asyncio.create_subprocess_exec` using `settings.CLAUDE_CLI_PATH`
     and the `-p` (print/headless) flag.
   - Pass the composed prompt (system + user) via argument and/or stdin per the
     CLI's contract; capture stdout as the result text.
   - Configurable timeout; on non-zero exit or timeout raise a typed
     `LLMRunnerError` with stderr context.
   - Keep prompt composition in a small helper so other runners can reuse it.
3. Register `ClaudeCodeRunner` under `llm_runner / "claude_code"` in bootstrap.
4. Provide a `FakeLLMRunner` (deterministic echo/templated output) registered as
   `llm_runner / "fake"` for tests and offline development.
5. Document the swap path (new `LLMRunner` subclass + registry name + config) in
   a docstring; full guide in Task 16.

## Files
- `app/llm/base.py`
- `app/llm/claude_code.py`
- `app/llm/fake.py`

## Acceptance Criteria
- `ClaudeCodeRunner.run()` shells out to `claude -p` and returns stdout text.
- Failures (timeout / non-zero exit / missing CLI) raise `LLMRunnerError`.
- `FakeLLMRunner` returns deterministic output with no external calls.
- Swapping runners requires only a config/registry change, no service edits.
