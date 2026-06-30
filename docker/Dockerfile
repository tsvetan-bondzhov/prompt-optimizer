# syntax=docker/dockerfile:1

# --- Prompt Optimizer application image -------------------------------------
# Base on a slim Python 3.12 image (project requires Python >=3.11).
FROM python:3.12-slim

# Sensible Python runtime defaults inside containers.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependency layer: copy only the project metadata first so that dependency
# installation is cached and not invalidated by every source change.
# We add a minimal README + package marker so the build backend can resolve
# the project before the full source tree is copied.
# ---------------------------------------------------------------------------
COPY pyproject.toml README.md ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install .

# ---------------------------------------------------------------------------
# Application source. Copied after dependencies for better layer caching.
# ---------------------------------------------------------------------------
COPY app ./app

# NOTE on the Claude Code CLI:
# The default PromptImprover / LLMRunner shells out to the Claude Code CLI
# (`claude -p`). It is intentionally NOT installed here and NO credentials are
# baked into the image. Provide the CLI at runtime by either:
#   * bind-mounting a host install into the container, or
#   * installing it in a derived image / entrypoint,
# and supply credentials via environment variables / mounted config at runtime.
# Override the executable location with the CLAUDE_CLI_PATH env var if needed.

EXPOSE 8000

# Default command: run the FastAPI app with uvicorn, listening on all
# interfaces so the mapped host port is reachable.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
