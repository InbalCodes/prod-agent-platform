"""Spec for the Settings exercise (src/agent_platform/config.py)."""

import pytest
from pydantic import ValidationError

from agent_platform.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_APP_NAME", "APP_ENVIRONMENT", "APP_LOG_LEVEL", "APP_LOG_JSON"):
        monkeypatch.delenv(name, raising=False)


def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "agent-platform"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.log_json is False


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_LOG_JSON", "true")

    settings = Settings(_env_file=None)

    assert settings.environment == "staging"
    assert settings.log_json is True


def test_ignores_unprefixed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")

    assert Settings(_env_file=None).environment == "local"


def test_invalid_environment_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")  # typo for "prod"

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOG_LEVEL", "debug")

    assert Settings(_env_file=None).log_level == "DEBUG"


def test_invalid_log_level_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_returns_a_single_instance() -> None:
    assert get_settings() is get_settings()
