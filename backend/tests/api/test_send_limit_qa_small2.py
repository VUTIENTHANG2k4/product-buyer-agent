"""QA lượt việc nhỏ 2 (T9.6): giới hạn gửi thử, biên thời gian, đa luồng, 404 không ghi nhận."""

import threading
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api import deps
from app.api.deps import get_notifiers, get_test_send_limiter
from app.domain.enums import AlertChannel
from app.main import create_app
from app.services.notifier.base import NotificationFailed, Notifier
from app.services.send_limiter import DEFAULT_INTERVAL_SECONDS, SendLimiter
from tests.api.test_alerts_api import create_alert, priced_product


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Recorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def send(self, destination: str, subject: str, body: str) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def use_notifiers(client: TestClient, notifiers: Mapping[AlertChannel, Notifier]) -> None:
    client.app.dependency_overrides[get_notifiers] = lambda: notifiers  # type: ignore[attr-defined]


@pytest.fixture
def limiter_and_clock(client: TestClient) -> tuple[SendLimiter, FakeClock]:
    clock = FakeClock()
    limiter = SendLimiter(clock=clock)
    client.app.dependency_overrides[get_test_send_limiter] = lambda: limiter  # type: ignore[attr-defined]
    return limiter, clock


# ---------------------------------------------------------------- biên thời gian của SendLimiter
def test_default_interval_is_ten_seconds() -> None:
    assert DEFAULT_INTERVAL_SECONDS == 10.0


def test_exactly_at_the_interval_the_send_is_allowed() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    limiter.try_acquire(1)

    clock.now += 10  # đúng bằng interval

    assert limiter.try_acquire(1) == 0


def test_one_instant_before_the_interval_is_still_blocked_with_at_least_one_second() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    limiter.try_acquire(1)

    clock.now += 10 - 1e-9

    assert limiter.try_acquire(1) == 1  # làm tròn lên: không bao giờ báo "chờ 0 giây" khi đang chặn


def test_a_rejected_attempt_does_not_extend_the_wait() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    limiter.try_acquire(1)
    for _ in range(5):
        clock.now += 1
        assert limiter.try_acquire(1) > 0  # bị chặn, không làm mới mốc

    clock.now += 5  # tổng 10 giây kể từ lần gửi thật

    assert limiter.try_acquire(1) == 0


@pytest.mark.parametrize("interval", [0, -5, 0.0])
def test_zero_or_negative_interval_never_blocks(interval: float) -> None:
    limiter = SendLimiter(interval, clock=FakeClock())

    assert [limiter.try_acquire(1) for _ in range(3)] == [0, 0, 0]


def test_fractional_interval_rounds_the_wait_up() -> None:
    limiter = SendLimiter(0.2, clock=FakeClock())
    limiter.try_acquire(1)

    assert limiter.try_acquire(1) == 1


def test_a_clock_that_goes_backwards_still_blocks_and_does_not_crash() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    limiter.try_acquire(1)

    clock.now -= 500  # đồng hồ lùi (monotonic thật không lùi, nhưng không được ngã)

    wait = limiter.try_acquire(1)
    assert isinstance(wait, int) and wait > 0


@pytest.mark.parametrize("key", [0, -1, 2**63, 10**30])
def test_any_integer_key_is_accepted(key: int) -> None:
    limiter = SendLimiter(10, clock=FakeClock())

    assert limiter.try_acquire(key) == 0
    assert limiter.try_acquire(key) == 10


# ---------------------------------------------------------------- bảng đầy 1000 mục
def test_full_table_of_live_entries_still_lets_a_new_key_through() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    for key in range(1000):
        limiter.try_acquire(key)
    clock.now += 5  # chưa mục nào hết hạn

    assert limiter.try_acquire(5000) == 0
    assert limiter.try_acquire(5000) > 0  # mục mới vẫn được theo dõi
    assert limiter.try_acquire(0) > 0  # mục cũ chưa hết hạn không bị quên (không né được giới hạn)


def test_table_below_the_cap_is_not_purged() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    for key in range(999):
        limiter.try_acquire(key)
    clock.now += 11  # hết hạn nhưng bảng chưa đầy

    limiter.try_acquire(-1)

    assert len(limiter._last) == 1000  # noqa: SLF001


def test_purge_keeps_live_entries_and_drops_only_expired_ones() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    for key in range(500):
        limiter.try_acquire(key)
    clock.now += 8
    for key in range(500, 1000):
        limiter.try_acquire(key)
    clock.now += 4  # nhóm đầu hết hạn (12 s), nhóm sau còn 8 s

    assert limiter.try_acquire(9999) == 0

    assert set(limiter._last) == {*range(500, 1000), 9999}  # noqa: SLF001
    assert limiter.try_acquire(700) > 0
    assert limiter.try_acquire(3) == 0


def test_many_threads_over_many_keys_let_exactly_one_per_key_through() -> None:
    limiter = SendLimiter(10, clock=FakeClock())
    keys, per_key = 50, 8
    barrier = threading.Barrier(keys * per_key)
    allowed: list[int] = []
    errors: list[BaseException] = []

    def attempt(key: int) -> None:
        try:
            barrier.wait()
            if limiter.try_acquire(key) == 0:
                allowed.append(key)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [
        threading.Thread(target=attempt, args=(key,)) for key in range(keys) for _ in range(per_key)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(allowed) == list(range(keys))


def test_concurrent_purges_on_a_full_table_never_raise() -> None:
    clock = FakeClock()
    limiter = SendLimiter(10, clock=clock)
    for key in range(1000):
        limiter.try_acquire(key)
    clock.now += 11
    errors: list[BaseException] = []

    def hammer(offset: int) -> None:
        try:
            for key in range(200):
                limiter.try_acquire(10_000 + offset * 1000 + key)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(hammer, range(8)))

    assert errors == []
    assert len(limiter._last) == 8 * 200  # noqa: SLF001


# ---------------------------------------------------------------- AlertService.send_test + API
def test_unconfigured_channel_is_not_counted_against_the_limit(
    client: TestClient, db_session: Session, limiter_and_clock: tuple[SendLimiter, FakeClock]
) -> None:
    limiter, _ = limiter_and_clock
    use_notifiers(client, {})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    first = client.post(f"/api/alerts/{alert_id}/test").json()
    second = client.post(f"/api/alerts/{alert_id}/test").json()

    assert "chưa được cấu hình" in first["reason"] and "chưa được cấu hình" in second["reason"]
    assert limiter._last == {}  # noqa: SLF001
    email = Recorder()
    use_notifiers(client, {AlertChannel.email: email})  # cấu hình xong: gửi được ngay
    assert client.post(f"/api/alerts/{alert_id}/test").json() == {"sent": True, "reason": None}
    assert email.calls == 1


@pytest.mark.parametrize("alert_id", [987654321, 0, -1, 2**31, 2**63, 10**30])
def test_missing_or_out_of_range_alert_is_404_and_not_recorded(
    client: TestClient, limiter_and_clock: tuple[SendLimiter, FakeClock], alert_id: int
) -> None:
    limiter, _ = limiter_and_clock
    email = Recorder()
    use_notifiers(client, {AlertChannel.email: email})

    first = client.post(f"/api/alerts/{alert_id}/test")
    second = client.post(f"/api/alerts/{alert_id}/test")

    assert first.status_code == second.status_code == 404
    assert first.json()["error"]["code"] == "ALERT_NOT_FOUND"
    assert email.calls == 0
    assert limiter._last == {}  # noqa: SLF001


@pytest.mark.parametrize("alert_id", ["abc", "1.5", "1e3", "%00"])
def test_non_integer_alert_id_is_422_and_not_recorded(
    client: TestClient, limiter_and_clock: tuple[SendLimiter, FakeClock], alert_id: str
) -> None:
    limiter, _ = limiter_and_clock
    use_notifiers(client, {AlertChannel.email: Recorder()})

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.status_code in (404, 422)
    assert limiter._last == {}  # noqa: SLF001


def test_a_deleted_alert_is_404_even_if_it_was_just_tested(
    client: TestClient, db_session: Session, limiter_and_clock: tuple[SendLimiter, FakeClock]
) -> None:
    use_notifiers(client, {AlertChannel.email: Recorder()})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]
    assert client.post(f"/api/alerts/{alert_id}/test").json()["sent"] is True
    client.delete(f"/api/alerts/{alert_id}")

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.status_code == 404


def test_the_second_call_is_allowed_again_after_the_interval(
    client: TestClient, db_session: Session, limiter_and_clock: tuple[SendLimiter, FakeClock]
) -> None:
    _, clock = limiter_and_clock
    email = Recorder()
    use_notifiers(client, {AlertChannel.email: email})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    assert client.post(f"/api/alerts/{alert_id}/test").json()["sent"] is True
    blocked = client.post(f"/api/alerts/{alert_id}/test").json()
    clock.now += 4
    still = client.post(f"/api/alerts/{alert_id}/test").json()
    clock.now += 6
    again = client.post(f"/api/alerts/{alert_id}/test").json()

    assert blocked == {"sent": False, "reason": "Vừa gửi thử cho cảnh báo này, thử lại sau 10 giây"}
    assert still["reason"].endswith("thử lại sau 6 giây")
    assert again == {"sent": True, "reason": None}
    assert email.calls == 2


def test_two_alerts_are_limited_independently(
    client: TestClient, db_session: Session, limiter_and_clock: tuple[SendLimiter, FakeClock]
) -> None:
    email = Recorder()
    use_notifiers(client, {AlertChannel.email: email})
    first = create_alert(client, priced_product(db_session)).json()["alert_id"]
    second = create_alert(client, priced_product(db_session)).json()["alert_id"]

    assert client.post(f"/api/alerts/{first}/test").json()["sent"] is True
    assert client.post(f"/api/alerts/{second}/test").json()["sent"] is True
    assert client.post(f"/api/alerts/{first}/test").json()["sent"] is False
    assert email.calls == 2


def test_a_failed_send_still_uses_the_window_but_is_reported_with_its_own_reason(
    client: TestClient, db_session: Session, limiter_and_clock: tuple[SendLimiter, FakeClock]
) -> None:
    email = Recorder(NotificationFailed("Không gửi được email (TimeoutError)"))
    use_notifiers(client, {AlertChannel.email: email})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    first = client.post(f"/api/alerts/{alert_id}/test").json()
    second = client.post(f"/api/alerts/{alert_id}/test").json()

    assert first == {"sent": False, "reason": "Không gửi được email (TimeoutError)"}
    assert "thử lại sau" in second["reason"]
    assert email.calls == 1


def test_an_unexpected_exception_does_not_leak_its_message(
    client: TestClient, db_session: Session, limiter_and_clock: tuple[SendLimiter, FakeClock]
) -> None:
    secret = "https://api.telegram.org/bot123456:SECRET-TOKEN/sendMessage"
    use_notifiers(client, {AlertChannel.email: Recorder(RuntimeError(secret))})
    alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]

    response = client.post(f"/api/alerts/{alert_id}/test")

    assert response.status_code == 200
    assert response.json() == {"sent": False, "reason": "Lỗi không xác định khi gửi thử"}
    assert "SECRET-TOKEN" not in response.text


# ---------------------------------------------------------------- bộ giới hạn mặc định của ứng dụng
@pytest.fixture
def app_limiter(monkeypatch: pytest.MonkeyPatch) -> Iterator[SendLimiter]:
    limiter = SendLimiter()
    monkeypatch.setattr(deps, "_TEST_SEND_LIMITER", limiter)
    yield limiter


def test_the_default_dependency_is_one_shared_instance(app_limiter: SendLimiter) -> None:
    assert get_test_send_limiter() is get_test_send_limiter() is app_limiter


def test_the_real_app_without_overrides_rate_limits_through_the_shared_limiter(
    db_session: Session, app_limiter: SendLimiter
) -> None:
    from app.api.deps import get_session
    from app.config import get_settings
    from tests.service_support import make_settings

    app = create_app()
    settings = make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    email = Recorder()
    app.dependency_overrides[get_notifiers] = lambda: {AlertChannel.email: email}
    with TestClient(app) as client:
        alert_id = create_alert(client, priced_product(db_session)).json()["alert_id"]
        first = client.post(f"/api/alerts/{alert_id}/test").json()
        second = client.post(f"/api/alerts/{alert_id}/test").json()

    assert first["sent"] is True and second["sent"] is False
    assert email.calls == 1
    assert alert_id in app_limiter._last  # noqa: SLF001
