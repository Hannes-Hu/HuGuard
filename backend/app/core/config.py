"""
Application settings loaded from environment / .env file.

Using pydantic-settings instead of raw os.environ gives us:
- Automatic type coercion and validation at startup (fail-fast)
- A single source of truth for every tuneable parameter
- IDE autocompletion across the entire codebase
"""

from functools import lru_cache
from pathlib import Path

import structlog
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen2.5-coder:7b")
    # Low temperature keeps structured JSON outputs stable; LLMs hallucinate
    # less-valid JSON when temperature > 0.3 with smaller models.
    ollama_temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    llm_timeout_seconds: int = Field(default=120, ge=10)

    # ── Persistence ───────────────────────────────────────────────────────────
    database_url: str = Field(default="sqlite+aiosqlite:///./data/huguard.db")

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    # Accepts comma-separated list or JSON array: "http://localhost:3000,http://..."
    cors_origins: str | list[str] = Field(default="http://localhost:3000")

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _split_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            # Check if it was passed as a JSON array string: '["http://..."]'
            clean_v = v.strip()
            if clean_v.startswith("[") and clean_v.endswith("]"):
                try:
                    import json
                    parsed = json.loads(clean_v)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except Exception as exc:
                    log.debug("Failed to parse cors_origins as JSON array", error=str(exc))
            return [origin.strip() for origin in clean_v.split(",") if origin.strip()]
        return v

    # ── File ingestion ────────────────────────────────────────────────────────
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024)
    upload_dir: Path = Field(default=Path("/app/uploads"))

    # ── Agent loop controls ───────────────────────────────────────────────────
    # Hard ceiling on critic retry cycles. Two retries is enough to catch
    # transient LLM failures without burning compute on a genuinely bad model.
    max_patch_retries: int = Field(default=2, ge=0, le=5)

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ── Security ──────────────────────────────────────────────────────────────
    secret_key: str = Field(default="change-me-in-production")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    @property
    def upload_dir_path(self) -> Path:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        return self.upload_dir


# lru_cache ensures we parse the env file exactly once per process lifetime.
# Tests override this by calling get_settings.cache_clear() before patching env.
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
