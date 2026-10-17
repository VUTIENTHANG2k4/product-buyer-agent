"""Ca biên của cấu hình: biến thiếu/rỗng/sai kiểu, lộ bí mật, mặc định an toàn."""

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _failed_fields(exc: pytest.ExceptionInfo[ValidationError]) -> set[str]:
    return {str(error["loc"][0]) for error in exc.value.errors()}


# --- Biến bắt buộc ---


@pytest.mark.parametrize(
    ("variable", "field"),
    [("DATABASE_URL", "database_url"), ("SCRAPER_USER_AGENT", "scraper_user_agent")],
)
def test_missing_required_variable_fails_naming_the_field(
    monkeypatch: pytest.MonkeyPatch, variable: str, field: str
) -> None:
    monkeypatch.delenv(variable)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert _failed_fields(exc) == {field}


@pytest.mark.parametrize("variable", ["DATABASE_URL", "SCRAPER_USER_AGENT"])
def test_empty_required_variable_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    # `VAR=` trong .env không được lọt qua như một giá trị hợp lệ.
    monkeypatch.setenv(variable, "")
    with pytest.raises(ValidationError):
        _settings()


def test_validation_error_message_does_not_leak_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:mat-khau-db@localhost/db")
    monkeypatch.setenv("AGENT_MAX_STEPS", "khong-phai-so")
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert "mat-khau-db" not in str(exc.value)


# --- Sai kiểu / ngoài miền giá trị ---


@pytest.mark.parametrize(
    ("variable", "value", "field"),
    [
        ("AGENT_MAX_STEPS", "tam", "agent_max_steps"),
        ("AGENT_MAX_STEPS", "3.5", "agent_max_steps"),
        ("POSTGRES_PORT", "cong-5432", "postgres_port"),
        ("SCRAPER_MIN_DELAY_SECONDS", "nhanh", "scraper_min_delay_seconds"),
        ("SCRAPER_OFFLINE_ONLY", "flase", "scraper_offline_only"),
        ("SCHEDULER_ENABLED", "co", "scheduler_enabled"),
        ("LLM_PROVIDER", "claude", "llm_provider"),
        ("ALERT_DEFAULT_CHANNEL", "sms", "alert_default_channel"),
    ],
)
def test_wrong_typed_or_unknown_value_fails_only_that_field(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, field: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert _failed_fields(exc) == {field}


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "on"])
def test_offline_only_truthy_spellings_parse_to_true(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SCRAPER_OFFLINE_ONLY", value)
    assert _settings().scraper_offline_only is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_offline_only_falsy_spellings_parse_to_false(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SCRAPER_OFFLINE_ONLY", value)
    assert _settings().scraper_offline_only is False


# --- Mặc định an toàn ---


def test_offline_only_defaults_to_true_when_variable_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCRAPER_OFFLINE_ONLY")
    assert _settings().scraper_offline_only is True


def test_offline_only_defaults_to_true_when_variable_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `SCRAPER_OFFLINE_ONLY=` (quên điền) không được vô tình bật chạy trang thật.
    monkeypatch.setenv("SCRAPER_OFFLINE_ONLY", "")
    assert _settings().scraper_offline_only is True


def test_env_example_ships_with_offline_only_enabled() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assert "SCRAPER_OFFLINE_ONLY=true" in [line.strip() for line in lines]


def test_non_secret_defaults_match_env_example() -> None:
    """Giá trị mẫu trong `.env.example` và mặc định trong `Settings` không được lệch nhau."""
    example: dict[str, str] = {}
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            example[key.lower()] = value
    mismatches: dict[str, tuple[object, object]] = {}
    for name, field in Settings.model_fields.items():
        value = example.get(name, "")
        if not value or field.is_required() or name.startswith("postgres_"):
            continue
        if "SecretStr" in str(field.annotation):
            continue
        parsed = getattr(Settings(_env_file=None, **{name: value}), name)  # type: ignore[call-arg]
        if parsed != field.default:
            mismatches[name] = (parsed, field.default)
    assert mismatches == {}


def test_get_settings_returns_one_cached_instance() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


# --- Không lộ bí mật ---

SECRET_VARIABLES = [
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "SMTP_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "CONTEXT7_API_KEY",
]


@pytest.fixture
def secret_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for variable in SECRET_VARIABLES:
        monkeypatch.setenv(variable, f"BI-MAT-{variable}")
    return _settings()


def test_every_secret_is_hidden_in_repr_and_str(secret_settings: Settings) -> None:
    for text in (repr(secret_settings), str(secret_settings)):
        assert "BI-MAT-" not in text


def test_every_secret_is_masked_in_model_dump_json(secret_settings: Settings) -> None:
    assert "BI-MAT-" not in secret_settings.model_dump_json()


def test_every_secret_is_hidden_in_python_dump_when_stringified(
    secret_settings: Settings,
) -> None:
    assert "BI-MAT-" not in str(secret_settings.model_dump())


def test_secrets_are_not_leaked_by_logging_the_settings_object(
    secret_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    logger = logging.getLogger("app.config.test")
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        logger.info("cấu hình: %s", secret_settings)
        logger.info("cấu hình: %r", secret_settings)
    assert "cấu hình" in caplog.text
    assert "BI-MAT-" not in caplog.text


def test_secret_fields_are_all_secretstr_so_new_secrets_cannot_regress() -> None:
    """Mọi field có tên giống bí mật phải là SecretStr (chặn field mới quên bọc)."""
    sensitive = ("key", "password", "token", "database_url")
    plain = [
        name
        for name, field in Settings.model_fields.items()
        if any(part in name for part in sensitive) and "SecretStr" not in str(field.annotation)
    ]
    assert plain == []


# --- Lỗ hổng đã biết: giá trị phi lý được chấp nhận (xfail strict: hết lỗi thì test báo để gỡ) ---

_BUG_NOTE = "Settings chưa ràng buộc miền giá trị (xem báo cáo QA M0)"


@pytest.mark.xfail(strict=True, reason=_BUG_NOTE)
@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SCRAPER_MIN_DELAY_SECONDS", "-1"),
        ("SCRAPER_MIN_DELAY_SECONDS", "nan"),
        ("SCRAPER_MIN_DELAY_SECONDS", "inf"),
        ("SCRAPER_TIMEOUT_SECONDS", "0"),
        ("SCRAPER_MAX_RETRIES", "-1"),
        ("SCRAPER_MAX_LISTING_PAGES", "0"),
        ("AGENT_MAX_STEPS", "0"),
        ("AGENT_MAX_STEPS", "-5"),
        ("POSTGRES_PORT", "70000"),
        ("SMTP_PORT", "0"),
    ],
)
def test_out_of_range_numeric_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.xfail(strict=True, reason=_BUG_NOTE)
def test_whitespace_only_user_agent_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # User-Agent trung thực là bắt buộc (CLAUDE.md): chuỗi toàn khoảng trắng không phải UA.
    monkeypatch.setenv("SCRAPER_USER_AGENT", "   ")
    with pytest.raises(ValidationError):
        _settings()
