# Task 16 — Documentation & Developer Guide

**Depends on:** all
**Milestone:** Hardening

## Objective
Document how to run, use, and extend the framework, and record project commands
for future contributors/agents.

## Steps
1. Update `README.md`:
   - Project overview (evaluator + optimizer).
   - Quick start with Docker (`docker compose -f docker/docker-compose.yml up`)
     and local dev (`uvicorn app.main:app --reload`).
   - Configuration reference (mirror plan §8 / `.env.example`).
   - Test command (`pytest`).
2. Developer extension guide (`docs/EXTENDING.md` or README section):
   - How to implement and register a `PromptExecutor`.
   - How to implement `EvaluationStep`s and `prepare_evaluation()` (note: no
     built-in LLM call — user supplies scoring logic).
   - How to implement a new `PromptImprover` / `Summarizer`.
   - How to add a new `LLMRunner` (Cursor / Copilot / Anthropic API) and select it
     via config — emphasize the swap path from Claude Code headless.
   - Where the `IMPROVER_SYSTEM_PROMPT` lives and how to edit it.
3. Usage guide: managing states & test cases, running a standalone validation,
   running an optimization loop, reading validation and optimization reports.
4. Architecture summary + link back to `Documents/Implementation/IMPLEMENTATION_PLAN.md`.
5. Create/append `AGENTS.md` at repo root recording: run command, test command,
   docker command, lint/format command, and key conventions discovered during
   implementation.

## Files
- `README.md`
- `docs/EXTENDING.md` (or README sections)
- `AGENTS.md`

## Acceptance Criteria
- A new developer can start the stack and run the reference end-to-end flow from the docs alone.
- Each extension point has a documented, copy-pasteable example.
- `AGENTS.md` records the canonical run/test/build commands.
