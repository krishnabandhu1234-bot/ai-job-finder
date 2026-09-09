"""Application configuration.

Two layers, deliberately kept separate:

1. `AppConfig` (this module) - environment/`.env`-derived, developer/deploy
   level settings: data directory, which AI providers to use, raw API keys,
   demo mode. Read once at startup. This is the ONLY place API keys are
   read from the environment; nothing else should call `os.environ` for a
   secret.

2. Runtime user preferences (job titles, locations, salary floor, minimum
   match score, schedule, etc.) live in the database (`user_preferences`,
   `settings` tables — see app/database/models.py) so they can be edited
   from the UI without restarting the app. See app/database/repository.py.

Never hardcode API keys or secrets. Values here either come from the
environment/.env file, or - for anything sensitive entered via the UI -
are encrypted before being written to the database (see core/security.py).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import paths
from app.core.constants import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIJF_",
        env_file=str(paths.project_root() / ".env") if not paths.is_frozen() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    demo_mode: bool = Field(default=True, alias="AIJF_DEMO_MODE")
    data_dir_override: str | None = Field(default=None, alias="AIJF_DATA_DIR")

    embedding_provider: EmbeddingProvider = Field(
        default=EmbeddingProvider.LOCAL, alias="AIJF_EMBEDDING_PROVIDER"
    )
    embedding_model: str = Field(default="all-MiniLM-L6-v2", alias="AIJF_EMBEDDING_MODEL")

    llm_provider: LLMProvider = Field(default=LLMProvider.NONE, alias="AIJF_LLM_PROVIDER")
    llm_model: str = Field(default="claude-sonnet-5", alias="AIJF_LLM_MODEL")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # A model running on this machine (Ollama, LM Studio, llama.cpp
    # server, ...) via its OpenAI-compatible endpoint - no API key, no
    # cost, nothing leaves the computer. Ollama's default is
    # http://localhost:11434/v1; set `llm_provider` to "local" and
    # `llm_model` to whatever model name you've pulled (e.g. "llama3.1").
    local_llm_base_url: str = Field(default="http://localhost:11434/v1", alias="AIJF_LOCAL_LLM_BASE_URL")

    smtp_host: str = Field(default="", alias="AIJF_SMTP_HOST")
    smtp_port: int = Field(default=587, alias="AIJF_SMTP_PORT")
    smtp_username: str = Field(default="", alias="AIJF_SMTP_USERNAME")
    smtp_app_password: str = Field(default="", alias="AIJF_SMTP_APP_PASSWORD")
    email_from: str = Field(default="", alias="AIJF_EMAIL_FROM")
    email_to: str = Field(default="", alias="AIJF_EMAIL_TO")

    encryption_key_override: str | None = Field(default=None, alias="AIJF_ENCRYPTION_KEY")

    log_level: str = Field(default="INFO", alias="AIJF_LOG_LEVEL")

    # Where to look for "is there a newer version of this app?" - a small
    # static JSON file (see app/core/updates.py for the shape). Empty by
    # default, which makes update checking completely inert rather than
    # pointing at a URL that doesn't exist yet.
    update_manifest_url: str = Field(default="", alias="AIJF_UPDATE_MANIFEST_URL")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {sorted(valid)}, got {v!r}")
        return upper

    @property
    def data_dir(self) -> Path:
        if self.data_dir_override:
            return Path(self.data_dir_override)
        return paths.default_data_dir()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "aijobfinder.db"

    @property
    def resumes_dir(self) -> Path:
        return self.data_dir / "resumes"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def has_llm_configured(self) -> bool:
        if self.llm_provider == LLMProvider.NONE:
            return False
        if self.llm_provider == LLMProvider.ANTHROPIC:
            return bool(self.anthropic_api_key)
        if self.llm_provider == LLMProvider.OPENAI:
            return bool(self.openai_api_key)
        if self.llm_provider == LLMProvider.GEMINI:
            return bool(self.gemini_api_key)
        if self.llm_provider == LLMProvider.LOCAL:
            return bool(self.local_llm_base_url and self.llm_model)
        return True

    def ensure_directories(self) -> None:
        for d in (self.data_dir, self.resumes_dir, self.logs_dir):
            paths.ensure_dir(d)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Process-wide singleton config, loaded once from env/.env."""
    config = AppConfig()
    config.ensure_directories()
    return config


def reload_config_for_tests() -> AppConfig:
    """Bypasses the cache — used by tests that need a fresh AppConfig()."""
    get_config.cache_clear()
    return get_config()
