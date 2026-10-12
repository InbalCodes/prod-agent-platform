"""Application configuration.

EXERCISE (Phase 0) — implement `Settings` and `get_settings`.
The executable spec is tests/unit/test_config.py.

Requirements:
- Settings are read from environment variables prefixed with `APP_`
  (e.g. APP_ENVIRONMENT=prod) and from a local `.env` file.
- Fields used by the rest of the app:
    app_name:    str          default "agent-platform"
    environment: Environment  default "local"
    log_level:   str          default "INFO"; case-insensitive input ("debug" -> "DEBUG");
                              must be a valid stdlib logging level name
    log_json:    bool         default False
- Invalid configuration must fail at startup (fail fast), not on first use.
- `get_settings()` returns the same instance on every call.

Docs: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
"""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    app_name: str = "agent-platform"
    environment: Environment = "local"
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        valid_levels = logging.getLevelNamesMapping()

        if normalized not in valid_levels:
            raise ValueError(
                f"Invalid log level: {value!r}. Allowed values: {', '.join(sorted(valid_levels))}"
            )

        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
