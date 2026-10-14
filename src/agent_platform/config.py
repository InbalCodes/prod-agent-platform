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
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_platform.llm.client import Effort

Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
        # `APP_ANTHROPIC_API_KEY=` (empty) means "not set", not "a key that is empty".
        env_ignore_empty=True,
    )

    app_name: str = "agent-platform"
    environment: Environment = "local"
    log_level: str = "INFO"
    log_json: bool = False

    # LLM. Optional locally so the service (and tests) run without a key;
    # required in every deployed environment (see the validator below).
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: Effort = "medium"
    # Per-attempt timeout. The SDK default is 10 minutes.
    llm_timeout_s: float = Field(default=25.0, gt=0)
    # SDK-level retries. 0: retry policy is owned by the workflow (ADR-0004), and
    # stacked retry layers multiply both load and worst-case latency.
    llm_max_retries: int = Field(default=0, ge=0, le=3)
    # Hard deadline for one investigation, below the load balancer idle timeout (60s).
    investigation_timeout_s: float = Field(default=50.0, gt=0)

    # V0 log source: one JSONL fixture file, path relative to the working directory.
    log_fixture_path: Path = Path("fixtures/logs/checkout-deploy-regression.jsonl")

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

    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> Self:
        if self.environment != "local" and self.anthropic_api_key is None:
            raise ValueError(f"APP_ANTHROPIC_API_KEY is required in {self.environment!r}")
        if self.investigation_timeout_s < self.llm_timeout_s:
            raise ValueError("investigation_timeout_s must be >= llm_timeout_s")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
