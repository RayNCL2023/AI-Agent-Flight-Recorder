"""Application configuration, loaded from environment variables / .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Every field can be set via environment variable."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "info"

    # --- storage ---
    database_url: str = "sqlite:///./data/flight_recorder.db"

    # --- LLM provider ---
    llm_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024

    # --- agent ---
    agent_max_steps: int = 12
    agent_tool_retry_limit: int = 1
    # Directory the file_reader tool is allowed to read from (sandbox root).
    file_reader_root: str = "./sample_data"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_path(self) -> Path | None:
        """Filesystem path of the SQLite database, if using SQLite."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix) :])
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
