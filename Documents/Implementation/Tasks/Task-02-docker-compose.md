# Task 02 — Docker & docker-compose

**Depends on:** 01
**Milestone:** Foundation

## Objective
Provide one-command local startup of the app + MongoDB.

## Steps
1. Create `docker/Dockerfile` for the app:
   - Base on `python:3.12-slim`.
   - Install dependencies (copy `pyproject.toml`/`requirements.txt` first for
     layer caching), then copy source.
   - If the default improver requires the Claude Code CLI, document that it must
     be provided at runtime (mounted/installed) — do **not** bake credentials in.
   - Expose port `8000`; default CMD runs `uvicorn app.main:app --host 0.0.0.0`.
2. Create `docker/docker-compose.yml`:
   - `mongo` service (official `mongo` image) with a named volume for data and a
     healthcheck.
   - `app` service built from the Dockerfile, `depends_on: mongo` (wait for
     healthy), env from `.env`, `MONGO_URI=mongodb://mongo:27017`.
   - Map `8000:8000`. Optionally bind-mount `app/implementations/` so developers
     can edit their pluggable implementations without rebuilding.
3. Add a `.dockerignore` (exclude `.venv`, `.git`, `__pycache__`, tests artifacts).
4. Document startup in README (Task 16): `docker compose -f docker/docker-compose.yml up`.

## Files
- `docker/Dockerfile`
- `docker/docker-compose.yml`
- `.dockerignore`

## Acceptance Criteria
- `docker compose up` starts both services; app reaches Mongo and serves the UI.
- Mongo data persists across restarts via the named volume.
- No secrets are baked into the image.
