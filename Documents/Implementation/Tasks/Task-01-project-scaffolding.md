# Task 01 — Project Scaffolding & Configuration

**Depends on:** none
**Milestone:** Foundation

## Objective
Create the Python project skeleton, dependency management, configuration system,
and logging so all later tasks have a consistent base.

## Steps
1. Create the package layout under `app/` per the plan (§7) with empty
   `__init__.py` files for: `app`, `db`, `db/repositories`, `models`, `core`,
   `llm`, `implementations`, `services`, `api`, `web`.
2. Choose dependency management (`pyproject.toml` with PEP 621, or
   `requirements.txt`). Add core deps:
   - `fastapi`, `uvicorn[standard]`
   - `motor` (async MongoDB), `pymongo`
   - `pydantic>=2`, `pydantic-settings`
   - `jinja2`, `python-multipart`
   - `sse-starlette` (or implement SSE manually with `StreamingResponse`)
   - Dev: `pytest`, `pytest-asyncio`, `httpx`, `mongomock-motor` (or test container)
3. Implement `app/config.py` using `pydantic-settings.BaseSettings` exposing all
   settings from plan §8, loaded from environment / `.env`. Provide a cached
   `get_settings()`.
4. Create `.env.example` documenting every variable with defaults.
5. Add a `logging` setup (structured/console) initialized at app startup.
6. Add `.gitignore` entries (`.env`, `__pycache__`, `.venv`, etc.) — extend the
   existing `.gitignore`.

## Files
- `pyproject.toml` (or `requirements.txt`)
- `app/__init__.py` and all sub-package `__init__.py`
- `app/config.py`
- `.env.example`
- `app/logging_config.py`

## Acceptance Criteria
- `python -c "from app.config import get_settings; print(get_settings())"` works.
- All settings from plan §8 are present with documented defaults.
- Importing the `app` package and sub-packages raises no errors.
