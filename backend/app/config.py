"""Cấu hình ứng dụng: nơi duy nhất đọc biến môi trường (docs/03 §8)."""

import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    Field,
    NonNegativeInt,
    PositiveInt,
    SecretStr,
    StringConstraints,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> thư mục gốc repo (nơi đặt file cấu hình môi trường)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# Miền giá trị hợp lệ: sai thì Settings() lỗi ngay lúc khởi động, không đợi tới nơi dùng.
NonNegativeSeconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Port = Annotated[int, Field(ge=1, le=65535)]


# User-Agent trung thực là bắt buộc (docs/02 §3): không nhận chuỗi rỗng hay toàn khoảng trắng.
def _check_user_agent(value: str) -> str:
    """Từ chối ký tự điều khiển (NUL, BEL, DEL, CR/LF…; tab được phép) và chuỗi toàn ký tự vô hình.

    Nếu không, h11 chỉ báo `LocalProtocolError` ở request đầu tiên thay vì lúc khởi động.
    """
    if any(unicodedata.category(char) == "Cc" and char != "	" for char in value):
        raise ValueError("must not contain control characters")
    if all(unicodedata.category(char) in ("Cf", "Zs", "Zl", "Zp") for char in value):
        raise ValueError("must contain visible characters")
    return value


UserAgent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(_check_user_agent)
]


# `mock-shop` là tên service trong docker-compose (T9.4): tên một nhãn, không có dấu chấm, chỉ phân
# giải được trong mạng của Compose nên không thể trỏ ra trang thật.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "mock-shop"})


def _check_mock_shop_url(value: str) -> str:
    """Mock-shop được miễn robots/ngoại tuyến/độ trễ trang thật nên chỉ được ở máy cục bộ."""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or parts.hostname not in LOCAL_HOSTS:
        raise ValueError("must be an http(s) URL on localhost, 127.0.0.1, ::1 or mock-shop")
    return value.rstrip("/")


MockShopUrl = Annotated[str, AfterValidator(_check_mock_shop_url)]

_ENV_CONFIG = SettingsConfigDict(
    env_file=ENV_FILE,
    env_file_encoding="utf-8",
    env_ignore_empty=True,
    extra="ignore",
)


class MockShopLocation(BaseSettings):
    """Chỉ `MOCK_SHOP_URL`, không có biến bắt buộc nào khác.

    `SiteConfig` của mock-shop cần địa chỉ lúc import module; đọc cả `Settings` thì import
    `app.scrapers.registry` đòi đủ biến môi trường (DATABASE_URL, SCRAPER_USER_AGENT…).
    """

    model_config = _ENV_CONFIG

    mock_shop_url: MockShopUrl = "http://localhost:8100"


class Settings(BaseSettings):
    """Mọi biến trong `.env.example`. Tên field = tên biến (không phân biệt hoa thường)."""

    model_config = _ENV_CONFIG

    # LLM
    llm_provider: Literal["gemini", "openai", "fake"] = "gemini"
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-mini"
    agent_max_steps: PositiveInt = 8
    # 0 = không giới hạn. Gói miễn phí của Gemini cho ~15 request/phút/model: đặt 12 khi chạy eval.
    llm_max_rpm: NonNegativeInt = 0
    llm_extractor_enabled: bool = True

    # Cơ sở dữ liệu (URL chứa mật khẩu nên là SecretStr; không có mặc định để khỏi hardcode).
    # test_database_url chỉ pytest dùng nên không bắt buộc khi chạy API/worker.
    postgres_user: str = "buyer"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "product_buyer"
    postgres_port: Port = 5432
    database_url: SecretStr
    test_database_url: SecretStr = SecretStr("")
    # Chỉ `make e2e` dùng. Bỏ trống thì suy ra từ DATABASE_URL (thêm hậu tố `_e2e` vào tên DB).
    e2e_database_url: SecretStr = SecretStr("")

    # Thu thập dữ liệu
    scraper_user_agent: UserAgent
    scraper_min_delay_seconds: NonNegativeSeconds = 5
    scraper_timeout_seconds: PositiveSeconds = 30
    scraper_max_retries: NonNegativeInt = 3
    scraper_max_listing_pages: PositiveInt = 3
    scraper_offline_only: bool = True

    # Mock-shop
    mock_shop_url: MockShopUrl = "http://localhost:8100"
    mock_shop_captcha_after: int = 5
    mock_shop_delay_seconds: float = 1

    # Lịch chạy
    scheduler_enabled: bool = False
    catalog_refresh_cron: str = "0 */12 * * *"
    tracked_refresh_cron: str = "0 */6 * * *"

    # Thông báo giá
    smtp_host: str = ""
    smtp_port: Port = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    alert_email_from: str = ""
    telegram_bot_token: SecretStr = SecretStr("")
    alert_default_channel: Literal["email", "telegram"] = "email"
    alert_default_email: str = ""
    telegram_chat_id: str = ""

    # Frontend / MCP (backend không dùng, khai báo để Settings phản ánh đủ .env.example)
    vite_api_base_url: str = "http://localhost:8000"
    context7_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_mock_shop_url() -> str:
    """Địa chỉ mock-shop (không có dấu `/` cuối), đọc nhẹ mà không cần đủ cấu hình."""
    return MockShopLocation().mock_shop_url
