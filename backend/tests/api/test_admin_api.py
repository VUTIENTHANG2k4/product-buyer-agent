"""API quản trị thu thập: /admin/sources, /admin/scrape-runs, challenge HITL (docs/07 §3.6).

Mock-shop chạy qua ASGI (không mạng). Tác vụ nền của API chạy trên event loop của TestClient;
`settle` chờ chúng xong trước khi test chạm DB tiếp (cả hai dùng chung một connection).
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_admin_service, get_scrape_service, get_session
from app.api.tasks import TaskRegistry
from app.config import Settings, get_settings
from app.db.models import Offer, ScrapeRun
from app.domain.enums import Category, ScrapeStatus, SiteKey
from app.main import create_app
from app.scrapers.http.robots import RobotsSnapshot
from app.scrapers.pipeline import BLOCK_COOLDOWN, NEEDS_HUMAN_STALE_AFTER, ScrapePipeline
from app.scrapers.registry import SCRAPERS
from app.services.admin_service import AdminService
from app.services.scrape_service import ScrapeService
from tests.factories import make_scrape_run
from tests.integration.test_pipeline import NOW, Clock, mock_fetcher
from tests.service_support import make_settings

INT4_OVER = 2**31


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def tasks_of(client: TestClient) -> TaskRegistry:
    app = cast(FastAPI, client.app)
    registry: TaskRegistry = app.state.tasks
    return registry


def settle(client: TestClient) -> None:
    """Chờ mọi tác vụ nền của app xong."""
    assert client.portal is not None
    client.portal.call(tasks_of(client).wait_all)


@contextmanager
def admin_client(
    db_session: Session, *, captcha_after: int = 10_000, offline: bool = True
) -> Iterator[tuple[TestClient, Clock]]:
    clock = Clock()
    bind = db_session.get_bind()

    def factory() -> Session:
        return Session(bind=bind, join_transaction_mode="create_savepoint")

    settings = Settings(scraper_offline_only=offline, scraper_max_listing_pages=5)
    fetcher = mock_fetcher(captcha_after=captcha_after)
    pipeline = ScrapePipeline(factory, fetcher, default_max_pages=5, now=clock)
    service = ScrapeService(factory, fetcher, settings, pipeline=pipeline, now=clock)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_scrape_service] = lambda: service
    app.dependency_overrides[get_admin_service] = lambda: AdminService(
        db_session, settings, now=clock
    )
    with TestClient(app) as client:
        yield client, clock


@pytest.fixture
def admin(db_session: Session) -> Iterator[tuple[TestClient, Clock]]:
    with admin_client(db_session) as pair:
        yield pair


def start_run(client: TestClient, **body: Any) -> Any:
    payload = {"site": "mockshop", "category": "laptop", **body}
    return client.post("/api/admin/scrape-runs", json=payload)


def captcha_answer(client: TestClient, run_id: int) -> str:
    prompt = client.get(f"/api/admin/scrape-runs/{run_id}/challenge").json()["prompt"]
    match = re.search(r"[A-Z2-9]{5}$", prompt)
    assert match, prompt
    return match.group(0)


# ---- bắt đầu lượt ----
def test_start_returns_202_with_run_id_then_the_run_finishes_in_the_background(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, _ = admin

    response = start_run(client)

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    settle(client)
    run = client.get(f"/api/admin/scrape-runs/{run_id}").json()
    assert run["status"] == "SUCCEEDED"
    assert (run["site"], run["category"], run["trigger"]) == ("mockshop", "laptop", "manual")
    assert run["pages_fetched"] > 0 and run["items_parsed"] > 0
    assert run["finished_at"] is not None and run["error_message"] is None
    assert run["challenge_kind"] is None
    db_session.expire_all()
    assert db_session.exec(select(Offer)).first() is not None
    assert tasks_of(client).pending == 0


def test_start_honours_max_pages(admin: tuple[TestClient, Clock]) -> None:
    client, _ = admin

    run_id = start_run(client, max_pages=1).json()["run_id"]
    settle(client)

    run = client.get(f"/api/admin/scrape-runs/{run_id}").json()
    assert run["pages_fetched"] == 1
    assert run["status"] == "PARTIAL"  # còn trang sau nhưng bị giới hạn bởi max_pages


def test_real_site_is_refused_while_offline_only_is_on(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, _ = admin

    response = start_run(client, site="gearvn")

    assert response.status_code == 409
    assert error_code(response) == "OFFLINE_MODE"
    assert response.json()["error"]["details"] == {"site": "gearvn"}
    assert db_session.exec(select(ScrapeRun)).all() == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"site": "mockshop"},
        {"site": "shopee", "category": "laptop"},
        {"site": "mockshop", "category": "toaster"},
        {"site": "mockshop", "category": "laptop", "max_pages": 0},
        {"site": "mockshop", "category": "laptop", "max_pages": 101},
        {"site": "mockshop", "category": "laptop", "max_pages": "many"},
    ],
)
def test_start_rejects_bad_bodies(admin: tuple[TestClient, Clock], payload: dict[str, Any]) -> None:
    client, _ = admin

    response = client.post("/api/admin/scrape-runs", json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_start_with_a_category_the_site_does_not_sell_is_validation_error(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, _ = admin

    response = start_run(client, category="phone")

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert db_session.exec(select(ScrapeRun)).all() == []


def test_start_while_another_run_is_active_is_409_and_names_it(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, clock = admin
    active = make_scrape_run(status=ScrapeStatus.RUNNING, started_at=clock.now)
    db_session.add(active)
    db_session.flush()

    response = start_run(client)

    assert response.status_code == 409
    assert error_code(response) == "SCRAPE_ALREADY_RUNNING"
    assert response.json()["error"]["details"]["run_id"] == active.id


def test_blocked_real_site_is_in_cooldown_and_start_is_409(db_session: Session) -> None:
    with admin_client(db_session, offline=False) as (client, clock):
        blocked = make_scrape_run(
            site=SiteKey.gearvn,
            status=ScrapeStatus.BLOCKED,
            started_at=clock.now - timedelta(hours=2),
        )
        db_session.add(blocked)
        db_session.flush()

        response = start_run(client, site="gearvn")

        assert response.status_code == 409
        assert error_code(response) == "SITE_COOLDOWN"
        retry_after = response.json()["error"]["details"]["retry_after"]
        assert retry_after.startswith((clock.now + timedelta(hours=22)).strftime("%Y-%m-%dT%H"))


# ---- challenge HITL ----
def test_captcha_flow_pauses_rejects_a_wrong_answer_then_finishes_after_the_right_one(
    db_session: Session,
) -> None:
    with admin_client(db_session, captcha_after=1) as (client, _):
        run_id = start_run(client).json()["run_id"]
        settle(client)

        paused = client.get(f"/api/admin/scrape-runs/{run_id}").json()
        assert paused["status"] == "NEEDS_HUMAN"
        assert paused["challenge_kind"] == "captcha"
        challenge = client.get(f"/api/admin/scrape-runs/{run_id}/challenge").json()
        assert challenge["kind"] == "captcha"
        assert challenge["prompt"]
        assert "token" not in challenge  # token chỉ dùng nội bộ để gửi đáp án

        wrong = client.post(f"/api/admin/scrape-runs/{run_id}/challenge", json={"answer": "ZZZZZ"})
        assert wrong.status_code == 400
        assert error_code(wrong) == "CHALLENGE_FAILED"
        assert client.get(f"/api/admin/scrape-runs/{run_id}").json()["status"] == "NEEDS_HUMAN"

        right = client.post(
            f"/api/admin/scrape-runs/{run_id}/challenge",
            json={"answer": captcha_answer(client, run_id).lower()},
        )
        assert right.status_code == 200
        assert right.json() == {"status": "RUNNING"}
        settle(client)

        done = client.get(f"/api/admin/scrape-runs/{run_id}").json()
        assert done["status"] == "SUCCEEDED"
        assert done["pages_fetched"] == 3
        assert done["challenge_kind"] is None
        again = client.get(f"/api/admin/scrape-runs/{run_id}/challenge")
        assert again.status_code == 409
        assert error_code(again) == "CHALLENGE_NOT_PENDING"


def test_answering_a_run_that_is_not_waiting_is_409(admin: tuple[TestClient, Clock]) -> None:
    client, _ = admin
    run_id = start_run(client).json()["run_id"]
    settle(client)

    response = client.post(f"/api/admin/scrape-runs/{run_id}/challenge", json={"answer": "ABCDE"})

    assert response.status_code == 409
    assert error_code(response) == "CHALLENGE_NOT_PENDING"
    assert response.json()["error"]["details"]["status"] == "SUCCEEDED"


def test_a_waiting_run_expires_after_an_hour_and_can_no_longer_be_answered(
    db_session: Session,
) -> None:
    with admin_client(db_session, captcha_after=1) as (client, clock):
        run_id = start_run(client).json()["run_id"]
        settle(client)
        clock.now += NEEDS_HUMAN_STALE_AFTER

        challenge = client.get(f"/api/admin/scrape-runs/{run_id}/challenge")
        answer = client.post(f"/api/admin/scrape-runs/{run_id}/challenge", json={"answer": "ABCDE"})

        assert challenge.status_code == answer.status_code == 409
        assert error_code(challenge) == error_code(answer) == "CHALLENGE_NOT_PENDING"


@pytest.mark.parametrize("answer", ["", "a\x00b", "x" * 201])
def test_answer_body_is_validated(db_session: Session, answer: str) -> None:
    with admin_client(db_session, captcha_after=1) as (client, _):
        run_id = start_run(client).json()["run_id"]
        settle(client)

        response = client.post(
            f"/api/admin/scrape-runs/{run_id}/challenge", json={"answer": answer}
        )

        assert response.status_code == 422


@pytest.mark.parametrize("run_id", ["999999", "0", "-3", str(INT4_OVER), str(2**70)])
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("get", "/challenge", None),
        ("post", "/challenge", {"answer": "ABCDE"}),
    ],
)
def test_unknown_or_out_of_range_run_id_is_404_run_not_found(
    admin: tuple[TestClient, Clock], run_id: str, method: str, suffix: str, body: Any
) -> None:
    client, _ = admin

    response = client.request(method, f"/api/admin/scrape-runs/{run_id}{suffix}", json=body)

    assert response.status_code == 404
    assert error_code(response) == "RUN_NOT_FOUND"


# ---- danh sách lượt ----
def test_runs_are_listed_newest_first_with_filters_and_pagination(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, clock = admin
    rows = [
        make_scrape_run(
            category=Category.mouse,
            status=ScrapeStatus.FAILED,
            started_at=clock.now - timedelta(hours=3),
        ),
        make_scrape_run(status=ScrapeStatus.SUCCEEDED, started_at=clock.now - timedelta(hours=2)),
        make_scrape_run(status=ScrapeStatus.SUCCEEDED, started_at=clock.now - timedelta(hours=1)),
        make_scrape_run(
            site=SiteKey.gearvn,
            status=ScrapeStatus.BLOCKED,
            started_at=clock.now - timedelta(hours=4),
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    ids = [row.id for row in rows]

    everything = client.get("/api/admin/scrape-runs").json()
    first_page = client.get("/api/admin/scrape-runs", params={"page_size": 2}).json()
    second_page = client.get("/api/admin/scrape-runs", params={"page_size": 2, "page": 2}).json()
    succeeded = client.get("/api/admin/scrape-runs", params={"status": "SUCCEEDED"}).json()
    gearvn = client.get("/api/admin/scrape-runs", params={"site": "gearvn"}).json()
    mouse = client.get("/api/admin/scrape-runs", params={"category": "mouse"}).json()

    assert [run["run_id"] for run in everything["items"]] == [ids[2], ids[1], ids[0], ids[3]]
    assert (everything["total"], everything["page"], everything["page_size"]) == (4, 1, 20)
    assert [run["run_id"] for run in first_page["items"]] == [ids[2], ids[1]]
    assert [run["run_id"] for run in second_page["items"]] == [ids[0], ids[3]]
    assert second_page["total"] == 4
    assert [run["run_id"] for run in succeeded["items"]] == [ids[2], ids[1]]
    assert [run["run_id"] for run in gearvn["items"]] == [ids[3]]
    assert [run["run_id"] for run in mouse["items"]] == [ids[0]]


@pytest.mark.parametrize(
    "params",
    [
        {"page_size": "101"},
        {"page": "0"},
        {"status": "DONE"},
        {"site": "shopee"},
        {"category": "x"},
    ],
)
def test_runs_list_rejects_bad_parameters(
    admin: tuple[TestClient, Clock], params: dict[str, str]
) -> None:
    client, _ = admin

    assert client.get("/api/admin/scrape-runs", params=params).status_code == 422


def test_run_detail_exposes_counters_and_the_error_message(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, _ = admin
    run = make_scrape_run(
        status=ScrapeStatus.FAILED,
        pages_fetched=2,
        items_parsed=30,
        items_failed=4,
        offers_upserted=26,
        price_changes=3,
        error_message="HTTP 500 tại trang 3",
    )
    db_session.add(run)
    db_session.flush()

    body = client.get(f"/api/admin/scrape-runs/{run.id}").json()

    assert (body["pages_fetched"], body["items_parsed"], body["items_failed"]) == (2, 30, 4)
    assert (body["offers_upserted"], body["price_changes"]) == (26, 3)
    assert body["error_message"] == "HTTP 500 tại trang 3"


# ---- nguồn ----
def test_sources_lists_every_registered_site_with_delay_and_last_run(
    admin: tuple[TestClient, Clock],
) -> None:
    client, _ = admin
    run_id = start_run(client).json()["run_id"]
    settle(client)

    items = {item["key"]: item for item in client.get("/api/admin/sources").json()["items"]}

    assert {"mockshop", "gearvn", "fptshop", "anphat"} <= set(items)
    mock = items["mockshop"]
    assert mock["is_mock"] is True and mock["enabled"] is True
    assert mock["robots_status"] == "allowed"
    assert mock["effective_delay_s"] == 0
    assert "laptop" in mock["categories"]
    assert mock["last_run"]["run_id"] == run_id
    assert mock["cooldown_until"] is None
    gearvn = items["gearvn"]
    assert gearvn["is_mock"] is False
    assert gearvn["robots_status"] == "unknown"  # chưa tải robots.txt trong tiến trình này
    assert gearvn["effective_delay_s"] >= 5
    assert gearvn["last_run"] is None


def test_sources_report_the_cooldown_of_a_blocked_real_site(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, clock = admin
    started = clock.now - timedelta(hours=2)
    db_session.add(
        make_scrape_run(site=SiteKey.gearvn, status=ScrapeStatus.BLOCKED, started_at=started)
    )
    db_session.flush()

    gearvn = next(
        item for item in client.get("/api/admin/sources").json()["items"] if item["key"] == "gearvn"
    )

    assert gearvn["last_run"]["status"] == "BLOCKED"
    assert gearvn["cooldown_until"].startswith(
        (started + BLOCK_COOLDOWN).strftime("%Y-%m-%dT%H:%M")
    )


def test_sources_no_longer_report_a_cooldown_after_it_has_passed(
    admin: tuple[TestClient, Clock], db_session: Session
) -> None:
    client, clock = admin
    started = clock.now - BLOCK_COOLDOWN - timedelta(minutes=1)
    db_session.add(
        make_scrape_run(site=SiteKey.gearvn, status=ScrapeStatus.BLOCKED, started_at=started)
    )
    db_session.flush()

    gearvn = next(
        item for item in client.get("/api/admin/sources").json()["items"] if item["key"] == "gearvn"
    )

    assert gearvn["cooldown_until"] is None


# ---- AdminService: robots.txt đã tải ----
@pytest.mark.parametrize(
    ("snapshot", "status", "crawl_delay"),
    [
        (None, "unknown", 0.0),
        (RobotsSnapshot("allowed", None), "allowed", 0.0),
        (RobotsSnapshot("partial", 60.0), "partial", 60.0),
        (RobotsSnapshot("partial", 1.0), "partial", 1.0),
    ],
)
def test_sources_use_the_cached_robots_snapshot_for_status_and_effective_delay(
    db_session: Session, snapshot: RobotsSnapshot | None, status: str, crawl_delay: float
) -> None:
    settings = make_settings(scraper_min_delay_seconds=5)
    service = AdminService(db_session, settings, robots=lambda url: snapshot)
    site_delay = SCRAPERS[SiteKey.gearvn].config.min_delay_s

    gearvn = next(view for view in service.sources() if view.key is SiteKey.gearvn)

    assert gearvn.robots_status == status
    assert gearvn.effective_delay_s == max(5.0, site_delay, crawl_delay)


def test_started_run_sets_manual_trigger_and_clock_time(
    admin: tuple[TestClient, Clock],
) -> None:
    client, clock = admin
    run_id = start_run(client).json()["run_id"]
    settle(client)

    run = client.get(f"/api/admin/scrape-runs/{run_id}").json()

    assert run["started_at"].startswith(NOW.strftime("%Y-%m-%dT%H:%M"))
    assert clock.now == NOW
