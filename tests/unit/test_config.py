"""Spec for the Settings exercise (src/agent_platform/config.py)."""

import pytest
from pydantic import ValidationError

from agent_platform.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_APP_NAME",
        "APP_ENVIRONMENT",
        "APP_LOG_LEVEL",
        "APP_LOG_JSON",
        "APP_ANTHROPIC_API_KEY",
        "APP_LLM_TIMEOUT_S",
        "APP_INVESTIGATION_TIMEOUT_S",
    ):
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
    monkeypatch.setenv("APP_ANTHROPIC_API_KEY", "sk-test")

    settings = Settings(_env_file=None)

    assert settings.environment == "staging"
    assert settings.log_json is True


def test_api_key_is_optional_only_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).anthropic_api_key is None

    monkeypatch.setenv("APP_ENVIRONMENT", "prod")
    with pytest.raises(ValidationError, match="APP_ANTHROPIC_API_KEY"):
        Settings(_env_file=None)


def test_empty_api_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ANTHROPIC_API_KEY", "")

    assert Settings(_env_file=None).anthropic_api_key is None


def test_api_key_is_never_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ANTHROPIC_API_KEY", "sk-super-secret")

    settings = Settings(_env_file=None)

    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in settings.model_dump_json()
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-super-secret"


def test_investigation_budget_must_fit_an_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LLM_TIMEOUT_S", "30")
    monkeypatch.setenv("APP_INVESTIGATION_TIMEOUT_S", "20")

    with pytest.raises(ValidationError, match="investigation_timeout_s"):
        Settings(_env_file=None)


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
