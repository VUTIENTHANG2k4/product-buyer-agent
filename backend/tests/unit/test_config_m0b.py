"""QA M0 lần hai: miền giá trị của cấu hình (T0.7) với dạng viết lạ và file .env giả.

Mọi file `.env` ở đây nằm trong `tmp_path`; không đọc `.env` thật của máy.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

DATABASE_URL = "postgresql+psycopg://u:p@h/d"


def _settings(**init: object) -> Settings:
    return Settings(_env_file=None, **init)  # type: ignore[call-arg]


def _failed(exc: pytest.ExceptionInfo[ValidationError]) -> dict[str, str]:
    return {str(e["loc"][0]): e["type"] for e in exc.value.errors()}


def _from_file(tmp_path: Path, text: str, **init: object) -> Settings:
    path = tmp_path / "qa.env"
    path.write_text(text, encoding="utf-8")
    return Settings(_env_file=path, **init)  # type: ignore[call-arg]


@pytest.fixture
def no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gỡ các biến do conftest đặt (UA, DB, độ trễ) để giá trị chỉ có thể đến từ file giả."""
    monkeypatch.delenv("SCRAPER_USER_AGENT")
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("SCRAPER_MIN_DELAY_SECONDS")


INT_FIELDS = [
    ("AGENT_MAX_STEPS", "agent_max_steps"),
    ("SCRAPER_MAX_RETRIES", "scraper_max_retries"),
    ("SCRAPER_MAX_LISTING_PAGES", "scraper_max_listing_pages"),
    ("POSTGRES_PORT", "postgres_port"),
    ("SMTP_PORT", "smtp_port"),
]
FLOAT_FIELDS = [
    ("SCRAPER_MIN_DELAY_SECONDS", "scraper_min_delay_seconds"),
    ("SCRAPER_TIMEOUT_SECONDS", "scraper_timeout_seconds"),
]


# --- Dạng viết lạ của số ---


@pytest.mark.parametrize(("variable", "field"), INT_FIELDS)
@pytest.mark.parametrize(
    "value",
    ["1e3", "0x10", "١٢٣", "１２", "True", "5.", "1,5", "5 6"],
    ids=["exp", "hex", "arabic-indic", "fullwidth", "bool-word", "trailing-dot", "comma", "space"],
)
def test_integer_setting_rejects_non_decimal_spellings(
    monkeypatch: pytest.MonkeyPatch, variable: str, field: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert _failed(exc) == {field: "int_parsing"}


@pytest.mark.parametrize(("variable", "field"), FLOAT_FIELDS)
@pytest.mark.parametrize(
    ("value", "error_type"),
    [
        ("0x10", "float_parsing"),
        ("١٢٣", "float_parsing"),
        ("True", "float_parsing"),
        ("1e400", "finite_number"),
        ("-Infinity", "finite_number"),
        ("NaN", "finite_number"),
    ],
)
def test_float_setting_rejects_non_decimal_and_non_finite_spellings(
    monkeypatch: pytest.MonkeyPatch, variable: str, field: str, value: str, error_type: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert _failed(exc) == {field: error_type}


@pytest.mark.parametrize(
    ("variable", "value", "field", "expected"),
    [
        ("AGENT_MAX_STEPS", "+5", "agent_max_steps", 5),
        ("AGENT_MAX_STEPS", "  5 ", "agent_max_steps", 5),
        ("AGENT_MAX_STEPS", "5.0", "agent_max_steps", 5),
        ("AGENT_MAX_STEPS", "007", "agent_max_steps", 7),
        ("SCRAPER_MAX_RETRIES", "0.0", "scraper_max_retries", 0),
        ("POSTGRES_PORT", "08080", "postgres_port", 8080),
        ("SMTP_PORT", "65535.0", "smtp_port", 65535),
        ("SCRAPER_MIN_DELAY_SECONDS", "1e3", "scraper_min_delay_seconds", 1000.0),
        ("SCRAPER_MIN_DELAY_SECONDS", ".5", "scraper_min_delay_seconds", 0.5),
        ("SCRAPER_TIMEOUT_SECONDS", " 2.5 ", "scraper_timeout_seconds", 2.5),
    ],
)
def test_lenient_but_unambiguous_spellings_are_normalized_to_the_plain_number(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, field: str, expected: float
) -> None:
    monkeypatch.setenv(variable, value)
    assert getattr(_settings(), field) == expected


@pytest.mark.parametrize("variable", ["POSTGRES_PORT", "SMTP_PORT"])
def test_port_far_beyond_the_valid_range_is_rejected_not_wrapped(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "9" * 30)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert set(_failed(exc).values()) == {"less_than_equal"}


@pytest.mark.parametrize(
    ("variable", "field"),
    [
        ("SCRAPER_MAX_LISTING_PAGES", "scraper_max_listing_pages"),
        ("AGENT_MAX_STEPS", "agent_max_steps"),
        ("POSTGRES_PORT", "postgres_port"),
    ],
)
@pytest.mark.parametrize("value", ["00", "-0", "-0000"])
def test_zero_in_any_spelling_is_rejected_where_zero_is_invalid(
    monkeypatch: pytest.MonkeyPatch, variable: str, field: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert set(_failed(exc)) == {field}


def test_every_invalid_setting_is_reported_at_once_not_one_per_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable, value in {
        "AGENT_MAX_STEPS": "0",
        "POSTGRES_PORT": "0",
        "SMTP_PORT": "99999",
        "SCRAPER_MAX_LISTING_PAGES": "0",
        "SCRAPER_TIMEOUT_SECONDS": "-1",
    }.items():
        monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert set(_failed(exc)) == {
        "agent_max_steps",
        "postgres_port",
        "smtp_port",
        "scraper_max_listing_pages",
        "scraper_timeout_seconds",
    }


# --- User-Agent ---


def test_user_agent_keeps_unicode_and_strips_unicode_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCRAPER_USER_AGENT", " 　Bôt/1.0 (liên hệ: a@b.vn) ☃ ")
    assert _settings().scraper_user_agent == "Bôt/1.0 (liên hệ: a@b.vn) ☃"


def test_user_agent_with_inner_tab_is_kept_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPER_USER_AGENT", "Bot/1.0\t(liên hệ)")
    assert _settings().scraper_user_agent == "Bot/1.0\t(liên hệ)"


def test_very_long_user_agent_is_stored_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    value = "Bot/1.0 " + "x" * 8000
    monkeypatch.setenv("SCRAPER_USER_AGENT", value)
    assert _settings().scraper_user_agent == value


@pytest.mark.parametrize(
    "value", ["Bot\x00x", "Bot\x07x", "Bot\x7fx", "​"], ids=["nul", "bel", "del", "zwsp"]
)
def test_user_agent_with_control_or_invisible_only_content_is_rejected_at_startup(
    tmp_path: Path, no_ambient_config: None, value: str
) -> None:
    text = f'DATABASE_URL={DATABASE_URL}\nSCRAPER_USER_AGENT="{value}"\n'
    with pytest.raises(ValidationError) as exc:
        _from_file(tmp_path, text)
    assert set(_failed(exc)) == {"scraper_user_agent"}


def test_quoted_whitespace_only_user_agent_in_env_file_is_rejected(
    tmp_path: Path, no_ambient_config: None
) -> None:
    text = f'DATABASE_URL={DATABASE_URL}\nSCRAPER_USER_AGENT="   "\n'
    with pytest.raises(ValidationError) as exc:
        _from_file(tmp_path, text)
    assert _failed(exc) == {"scraper_user_agent": "string_too_short"}


def test_blank_user_agent_in_env_file_counts_as_missing(
    tmp_path: Path, no_ambient_config: None
) -> None:
    with pytest.raises(ValidationError) as exc:
        _from_file(tmp_path, f"DATABASE_URL={DATABASE_URL}\nSCRAPER_USER_AGENT=\n")
    assert _failed(exc) == {"scraper_user_agent": "missing"}


def test_user_agent_in_env_file_loses_inline_comment_and_bom(
    tmp_path: Path, no_ambient_config: None
) -> None:
    text = f"﻿DATABASE_URL={DATABASE_URL}\nSCRAPER_USER_AGENT=Bot/1.0 # liên hệ sau\n"
    assert _from_file(tmp_path, text).scraper_user_agent == "Bot/1.0"


def test_explicit_empty_user_agent_argument_is_rejected_even_if_environment_has_one() -> None:
    with pytest.raises(ValidationError) as exc:
        _settings(scraper_user_agent="")
    assert _failed(exc) == {"scraper_user_agent": "string_too_short"}


# --- File .env giả và thứ tự ưu tiên ---


def test_values_are_read_from_the_env_file_with_the_same_range_rules(
    tmp_path: Path, no_ambient_config: None
) -> None:
    text = (
        f"DATABASE_URL={DATABASE_URL}\nSCRAPER_USER_AGENT=file/1.0\nAGENT_MAX_STEPS=4\n"
        "POSTGRES_PORT=6543\nSCRAPER_MIN_DELAY_SECONDS=2.5\n"
    )
    settings = _from_file(tmp_path, text)
    assert (settings.agent_max_steps, settings.postgres_port) == (4, 6543)
    assert settings.scraper_min_delay_seconds == 2.5
    assert settings.scraper_user_agent == "file/1.0"
    assert settings.database_url.get_secret_value() == DATABASE_URL


@pytest.mark.parametrize(
    ("line", "field"),
    [
        ("AGENT_MAX_STEPS=0", "agent_max_steps"),
        ("POSTGRES_PORT=70000", "postgres_port"),
        ("SCRAPER_MIN_DELAY_SECONDS=-1", "scraper_min_delay_seconds"),
        ("SCRAPER_TIMEOUT_SECONDS=nan", "scraper_timeout_seconds"),
    ],
)
def test_out_of_range_value_in_env_file_is_rejected(
    tmp_path: Path, no_ambient_config: None, line: str, field: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        _from_file(tmp_path, f"{line}\n")
    assert field in _failed(exc)


def test_environment_variable_beats_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_MAX_STEPS", "7")
    assert _from_file(tmp_path, "AGENT_MAX_STEPS=4\n").agent_max_steps == 7


def test_invalid_environment_variable_does_not_fall_back_to_a_valid_file_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_MAX_STEPS", "0")
    with pytest.raises(ValidationError) as exc:
        _from_file(tmp_path, "AGENT_MAX_STEPS=4\n")
    assert _failed(exc) == {"agent_max_steps": "greater_than"}


def test_empty_environment_variable_falls_back_to_the_file_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_MAX_STEPS", "")
    assert _from_file(tmp_path, "AGENT_MAX_STEPS=4\n").agent_max_steps == 4


def test_init_argument_beats_environment_and_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_MAX_STEPS", "7")
    assert _from_file(tmp_path, "AGENT_MAX_STEPS=4\n", agent_max_steps=9).agent_max_steps == 9


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_max_steps", 0),
        ("postgres_port", 70000),
        ("scraper_min_delay_seconds", float("nan")),
        ("scraper_timeout_seconds", 0),
    ],
)
def test_range_rules_also_apply_to_init_arguments(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as exc:
        _settings(**{field: value})
    assert field in _failed(exc)


def test_env_file_with_blank_offline_flag_keeps_the_safe_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SCRAPER_OFFLINE_ONLY")
    assert _from_file(tmp_path, "SCRAPER_OFFLINE_ONLY=\n").scraper_offline_only is True


def test_unknown_keys_and_lowercase_or_export_forms_in_env_file_are_tolerated(
    tmp_path: Path,
) -> None:
    text = "UNKNOWN_KEY=1\nagent_max_steps=4\nexport SCRAPER_MAX_RETRIES=2\n"
    settings = _from_file(tmp_path, text)
    assert (settings.agent_max_steps, settings.scraper_max_retries) == (4, 2)


def test_missing_env_file_path_is_not_an_error_when_the_environment_is_complete(
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=tmp_path / "khong-ton-tai.env")  # type: ignore[call-arg]
    assert settings.agent_max_steps == 8
