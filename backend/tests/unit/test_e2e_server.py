"""Hàm thuần của `scripts/e2e_server.py`: chọn DB E2E an toàn và môi trường tiến trình con."""

import os
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from scripts import e2e_server
from scripts.e2e_server import (
    UnsafeE2eDatabase,
    admin_url,
    derive_e2e_url,
    e2e_environment,
)

DEV_URL = "postgresql+psycopg://buyer:secret@127.0.0.1:5432/product_buyer"


class TestDeriveE2eUrl:
    def test_appends_suffix_to_database_name_when_no_explicit_url(self) -> None:
        url = derive_e2e_url(DEV_URL)

        assert url.database == "product_buyer_e2e"
        assert url.host == "127.0.0.1"
        assert url.port == 5432
        assert url.username == "buyer"

    def test_does_not_double_the_suffix_when_database_url_already_ends_with_it(self) -> None:
        url = derive_e2e_url("postgresql+psycopg://buyer:secret@127.0.0.1:5432/shop_e2e")

        assert url.database == "shop_e2e"

    def test_uses_explicit_url_when_given(self) -> None:
        explicit = "postgresql+psycopg://other:pw@db.internal:6543/custom_e2e"

        url = derive_e2e_url(DEV_URL, explicit)

        assert (url.database, url.host, url.port) == ("custom_e2e", "db.internal", 6543)

    @pytest.mark.parametrize(
        "explicit",
        [
            "postgresql+psycopg://buyer:secret@127.0.0.1:5432/product_buyer",
            "postgresql+psycopg://buyer:secret@127.0.0.1:5432/product_buyer_test",
            "postgresql+psycopg://buyer:secret@127.0.0.1:5432/e2e",
            "postgresql+psycopg://buyer:secret@127.0.0.1:5432/product_buyer_e2e_old",
            "postgresql+psycopg://buyer:secret@127.0.0.1:5432/_e2e",
            "postgresql+psycopg://buyer:secret@127.0.0.1:5432/",
        ],
    )
    def test_refuses_explicit_database_not_ending_with_e2e(self, explicit: str) -> None:
        with pytest.raises(UnsafeE2eDatabase):
            derive_e2e_url(DEV_URL, explicit)

    def test_whitespace_only_explicit_url_falls_back_to_derived_name(self) -> None:
        assert derive_e2e_url(DEV_URL, "   ").database == "product_buyer_e2e"

    def test_derived_name_from_test_database_keeps_dev_data_untouched(self) -> None:
        url = derive_e2e_url("postgresql+psycopg://buyer:pw@localhost:5432/product_buyer_test")

        assert url.database == "product_buyer_test_e2e"


class TestEnvironment:
    def test_points_database_at_e2e_and_forces_fake_llm_and_offline(self) -> None:
        url = make_url("postgresql+psycopg://buyer:secret@127.0.0.1:5432/product_buyer_e2e")

        env = e2e_environment(
            url,
            {
                "DATABASE_URL": DEV_URL,
                "LLM_PROVIDER": "gemini",
                "SCRAPER_OFFLINE_ONLY": "false",
                "KEEP": "1",
            },
        )

        assert env["DATABASE_URL"].endswith("/product_buyer_e2e")
        assert "secret" in env["DATABASE_URL"]
        assert env["LLM_PROVIDER"] == "fake"
        assert env["SCRAPER_OFFLINE_ONLY"] == "true"
        assert env["KEEP"] == "1"

    def test_does_not_modify_the_mapping_it_was_given(self) -> None:
        base = {"DATABASE_URL": DEV_URL}

        e2e_environment(make_url(DEV_URL + "_e2e"), base)

        assert base == {"DATABASE_URL": DEV_URL}


def test_admin_url_targets_postgres_database_on_same_server() -> None:
    url = admin_url(make_url("postgresql+psycopg://buyer:secret@127.0.0.1:5435/product_buyer_e2e"))

    assert (url.database, url.host, url.port, url.username) == (
        "postgres",
        "127.0.0.1",
        5435,
        "buyer",
    )


class TestMainGuard:
    """`main()` phải dừng TRƯỚC mọi thao tác phá hủy khi tên DB không an toàn."""

    @staticmethod
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "không được chạm DB, migrate, seed hay chạy API khi tên DB không an toàn"
        )

    def test_refuses_unsafe_explicit_database_without_touching_anything(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = SimpleNamespace(
            database_url=SecretStr(DEV_URL),
            e2e_database_url=SecretStr(DEV_URL),  # chính DB dev: tuyệt đối không được reset
        )
        monkeypatch.setattr(e2e_server, "get_settings", lambda: settings)
        monkeypatch.setattr(e2e_server, "ensure_database", self._boom)
        monkeypatch.setattr(e2e_server, "_run", self._boom)
        monkeypatch.setattr(uvicorn, "run", self._boom)

        with caplog.at_level("ERROR", logger="e2e_server"):
            code = e2e_server.main(["--port", "8099"])

        assert code == 2
        assert "_e2e" in caplog.text

    def test_safe_database_runs_migrate_then_seed_reset_then_serves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = SimpleNamespace(database_url=SecretStr(DEV_URL), e2e_database_url=SecretStr(""))
        steps: list[str] = []

        def ensure(url: Any) -> bool:
            steps.append(f"ensure {url.database}")
            return True

        def run(args: Any, env: Any) -> None:
            steps.append(f"{' '.join(args)} -> {make_url(env['DATABASE_URL']).database}")

        def serve(*_args: Any, **kwargs: Any) -> None:
            steps.append(f"serve {kwargs['port']}")

        monkeypatch.setattr(e2e_server, "get_settings", _cache_clearable(settings))
        monkeypatch.setattr(e2e_server, "ensure_database", ensure)
        monkeypatch.setattr(e2e_server, "_run", run)
        monkeypatch.setattr(uvicorn, "run", serve)
        monkeypatch.setattr(os, "environ", {})

        assert e2e_server.main(["--port", "8099"]) == 0

        assert steps == [
            "ensure product_buyer_e2e",
            "alembic upgrade head -> product_buyer_e2e",
            "scripts.seed --fixture e2e --reset --yes -> product_buyer_e2e",
            "serve 8099",
        ]


def _cache_clearable(settings: SimpleNamespace):  # type: ignore[no-untyped-def]
    """`main()` gọi `get_settings.cache_clear()`: bản giả cần có thuộc tính đó."""

    def fake() -> SimpleNamespace:
        return settings

    fake.cache_clear = lambda: None  # type: ignore[attr-defined]
    return fake
