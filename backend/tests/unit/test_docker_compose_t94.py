"""T9.4: docker-compose.yml và Dockerfile đúng thiết kế docs/10 §4 (đọc tệp, không chạy Docker)."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES: dict[str, dict[str, Any]] = COMPOSE["services"]


def test_compose_defines_the_five_services_of_the_design() -> None:
    assert set(SERVICES) == {"db", "api", "worker", "mock-shop", "web"}


@pytest.mark.parametrize("name", ["api", "worker", "mock-shop"])
def test_backend_services_share_one_image_and_the_compose_database_and_mock_shop_hosts(
    name: str,
) -> None:
    service = SERVICES[name]

    assert service["build"] == "./backend"
    assert service["image"] == "product-buyer-backend:local"
    assert "@db:5432/" in service["environment"]["DATABASE_URL"]
    assert service["environment"]["MOCK_SHOP_URL"] == "http://mock-shop:8100"
    assert service["env_file"] == ".env"


def test_commands_match_the_design() -> None:
    assert SERVICES["api"]["command"][-1].startswith("alembic upgrade head && exec uvicorn")
    assert "app.main:app" in SERVICES["api"]["command"][-1]
    assert SERVICES["worker"]["command"] == ["python", "-m", "app.worker"]
    assert SERVICES["mock-shop"]["command"][:2] == ["uvicorn", "app.mock_shop.main:app"]


def test_start_order_waits_for_a_healthy_database_and_migrated_api() -> None:
    assert SERVICES["api"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert SERVICES["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert SERVICES["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "healthcheck" in SERVICES["api"] and "healthcheck" in SERVICES["db"]


def test_every_published_port_is_bound_to_localhost() -> None:
    ports = [port for service in SERVICES.values() for port in service.get("ports", [])]

    assert ports and all(str(port).startswith("127.0.0.1:") for port in ports)


def test_worker_is_not_restarted_after_a_clean_exit_and_retries_a_bounded_number_of_times() -> None:
    # SCHEDULER_ENABLED=false làm worker thoát mã 0: `unless-stopped` sẽ khởi động lại mãi;
    # cấu hình sai (mã khác 0) không được lặp vô hạn.
    assert SERVICES["worker"]["restart"] == "on-failure:5"


def test_backend_containers_share_a_named_volume_the_unprivileged_user_can_write() -> None:
    for name in ("api", "worker", "mock-shop"):
        assert SERVICES[name]["volumes"] == ["appdata:/app/data"]
    assert "appdata" in COMPOSE["volumes"]


def test_no_secret_value_is_written_in_the_compose_file() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert not re.search(r"(?i)(api_key|token|smtp_password)\s*[:=]\s*[^\s$]", text)
    # Mật khẩu DB chỉ được tham chiếu qua biến, không viết cứng.
    assert "POSTGRES_PASSWORD}" in text and "postgresql+psycopg://buyer:" not in text


def test_backend_image_runs_unprivileged_and_never_contains_env_files() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    ignore = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert re.search(r"^USER buyer$", dockerfile, re.M)
    assert "--no-dev" in dockerfile and "--locked" in dockerfile
    assert ".env" in ignore and ".env.*" in ignore
    assert not re.search(r"COPY .*\.env", dockerfile)


def test_seed_fixtures_are_the_only_part_of_tests_copied_into_the_image() -> None:
    ignore = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert {"tests/*", "!tests/fixtures", "tests/fixtures/*", "!tests/fixtures/seed"} <= set(ignore)
    assert (ROOT / "backend" / "tests" / "fixtures" / "seed").is_dir()


def test_web_image_proxies_api_without_buffering_and_falls_back_to_the_spa() -> None:
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert "location /api/" in nginx and "http://api:8000" in nginx
    # Phân giải lại tên api qua DNS Docker: tạo lại container api không làm web trả 502.
    assert "resolver 127.0.0.11" in nginx and "proxy_pass $api_upstream;" in nginx
    assert "proxy_set_header Host $http_host;" in nginx  # giữ cổng
    assert "proxy_buffering off;" in nginx  # luồng SSE phải tới trình duyệt ngay
    assert "try_files $uri /index.html;" in nginx
    assert 'ENV VITE_API_BASE_URL=""' in dockerfile
    assert "FROM nginx:" in dockerfile
