from pathlib import Path

import pytest

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _example_keys() -> set[str]:
    keys: set[str] = set()
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].lower())
    return keys


def test_settings_cover_every_env_example_variable() -> None:
    assert _example_keys() == set(Settings.model_fields)


def test_values_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MAX_STEPS", "3")
    monkeypatch.setenv("SCRAPER_OFFLINE_ONLY", "false")
    monkeypatch.setenv("GOOGLE_API_KEY", "khoa-bi-mat")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_max_steps == 3
    assert settings.scraper_offline_only is False
    assert settings.google_api_key.get_secret_value() == "khoa-bi-mat"
    assert "khoa-bi-mat" not in repr(settings)


def test_empty_variable_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.gemini_model == "gemini-3.5-flash-lite"


def test_database_urls_use_psycopg3_driver() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert settings.test_database_url.get_secret_value().startswith("postgresql+psycopg://")


def test_database_password_is_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:mat-khau-db@localhost/db")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "mat-khau-db" not in repr(settings)


def test_test_database_url_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.test_database_url.get_secret_value() == ""
