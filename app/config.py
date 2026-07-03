"""Application configuration via pydantic-settings.

All settings can be overridden through environment variables or a local ``.env``
file. Use :func:`get_settings` (cached) to access the active configuration.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Default optimizer system prompt. Kept as an easily editable module-level
# constant per the implementation plan (§8).
DEFAULT_OPTIMIZER_SYSTEM_PROMPT = (
    "You are an expert prompt engineer. Given a goal, the current prompt, its "
    "measured strengths and weaknesses, the current average score, and the "
    "reasoning behind it, produce an improved prompt that better satisfies the "
    "goal across all test cases. Return only the improved prompt text."
)


class Settings(BaseSettings):
    """Strongly-typed application settings (see implementation plan §8)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- MongoDB ---------------------------------------------------------
    MONGO_URI: str = "mongodb://mongo:27017"
    MONGO_DB: str = "prompt_optimizer"

    # --- Active registry implementations ---------------------------------
    ACTIVE_EXECUTOR: str = "default"
    ACTIVE_OPTIMIZER: str = "claude_code"
    ACTIVE_SUMMARIZER: str = "default"
    ACTIVE_LLM_RUNNER: str = "claude_code"

    # --- Claude Code CLI -------------------------------------------------
    CLAUDE_CLI_PATH: str = "claude"

    # --- Ollama (local) ---------------------------------------------------
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "mistral"
    OLLAMA_TIMEOUT_SECONDS: float = 120.0

    # --- Optimization / evaluation defaults ------------------------------
    DEFAULT_EXECUTIONS_PER_TEST_CASE: int = 1
    DEFAULT_TARGET_SCORE: float = 9.0
    DEFAULT_MAX_ITERATIONS: int = 10

    # --- JSON evaluation steps --------------------------------------------
    # When true, the JSON evaluation steps tolerate output wrapped in a
    # Markdown code fence (```json ... ```). When false (default), pure JSON
    # is expected and fenced output fails parsing (scores 1).
    JSON_EVAL_ALLOW_MARKDOWN: bool = False

    # --- Optimizer prompt -------------------------------------------------
    OPTIMIZER_SYSTEM_PROMPT: str = DEFAULT_OPTIMIZER_SYSTEM_PROMPT

    # --- Logging ----------------------------------------------------------
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()
