"""X4: thử lại lời gọi LLM khi lỗi tạm thời (`app/agent/llm_retry.py`).

Không gọi mạng, không chờ thật: hàm `sleep` và `random` của `RetryPolicy` được thay bằng bản ghi.
"""

import asyncio
import logging
from collections.abc import Callable

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from app.agent.llm_retry import (
    NO_RETRY,
    RetryPolicy,
    call_with_retry,
    is_transient,
    status_of,
)
from app.agent.testing import ScriptExhausted
from app.config import Settings
from tests.service_support import make_settings


class ApiError(Exception):
    """Giống lỗi của SDK: mang mã HTTP ở `code` (google-genai) hoặc `status_code` (openai)."""

    def __init__(self, code: int, attr: str = "code") -> None:
        super().__init__(f"{code} error")
        setattr(self, attr, code)


def wrapped(inner: BaseException) -> Exception:
    """Lỗi LangChain bọc lỗi SDK trong `__cause__`."""
    try:
        raise inner
    except BaseException as error:
        try:
            raise RuntimeError("wrapper") from error
        except RuntimeError as outer:
            return outer


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def policy(sleeps: Sleeps, **overrides: float) -> RetryPolicy:
    values = {
        "attempts": 3,
        "base_delay_s": 2.0,
        "max_delay_s": 10.0,
        "max_total_wait_s": 20.0,
        **overrides,
    }
    return RetryPolicy(
        attempts=int(values["attempts"]),
        base_delay_s=values["base_delay_s"],
        max_delay_s=values["max_delay_s"],
        max_total_wait_s=values["max_total_wait_s"],
        sleep=sleeps,
        random=lambda: 1.0,  # hệ số ngẫu nhiên lớn nhất: chờ đúng bằng trần công thức
    )


def failing(errors: list[BaseException], result: str = "ok") -> Callable[[], "asyncio.Future[str]"]:
    calls = {"n": 0}

    def call() -> "asyncio.Future[str]":
        calls["n"] += 1
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        if errors:
            future.set_exception(errors.pop(0))
        else:
            future.set_result(result)
        return future

    call.calls = calls  # type: ignore[attr-defined]
    return call


# ---- phân loại lỗi ----
@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_http_codes_are_retried(code: int) -> None:
    assert is_transient(ApiError(code))
    assert is_transient(ApiError(code, attr="status_code"))
    assert is_transient(wrapped(ApiError(code)))  # mã nằm ở lỗi gốc bị LangChain bọc


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(code: int) -> None:
    assert not is_transient(ApiError(code))
    assert not is_transient(wrapped(ApiError(code)))


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("read timed out"),
        TimeoutError(),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
)
def test_timeouts_and_connection_errors_are_retried(error: BaseException) -> None:
    assert is_transient(error)
    assert is_transient(wrapped(error))


def test_data_errors_are_not_retried() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings.model_validate({"llm_retry_attempts": "x"})
    for error in (
        caught.value,
        OutputParserException("bad json"),
        ValueError("bad"),
        ScriptExhausted("hết kịch bản"),
        RuntimeError("bug"),
    ):
        assert not is_transient(error)


def test_status_ignores_non_http_codes_and_booleans() -> None:
    weird = ApiError(503)
    weird.code = True  # type: ignore[attr-defined]
    assert status_of(weird) is None
    errno_like = ApiError(2)  # `code` kiểu errno, không phải HTTP
    assert status_of(errno_like) is None and not is_transient(errno_like)


def test_a_cause_cycle_does_not_loop_forever() -> None:
    first, second = RuntimeError("a"), RuntimeError("b")
    first.__cause__, second.__cause__ = second, first
    assert not is_transient(first)


# ---- giãn cách ----
def test_delay_doubles_until_the_cap_and_jitter_halves_at_most() -> None:
    sleeps = Sleeps()
    full = policy(sleeps)
    assert [full.delay(n) for n in (1, 2, 3, 4)] == [2.0, 4.0, 8.0, 10.0]
    half = RetryPolicy(base_delay_s=2.0, max_delay_s=10.0, random=lambda: 0.0)
    assert [half.delay(n) for n in (1, 2, 4)] == [1.0, 2.0, 5.0]


# ---- call_with_retry ----
async def test_a_transient_error_then_success_returns_the_result_after_one_pause() -> None:
    sleeps = Sleeps()
    call = failing([ApiError(503)])

    assert await call_with_retry(call, policy(sleeps)) == "ok"

    assert call.calls["n"] == 2  # type: ignore[attr-defined]
    assert sleeps.calls == [2.0]


async def test_attempts_are_capped_and_the_last_error_is_raised() -> None:
    sleeps = Sleeps()
    errors: list[BaseException] = [ApiError(503), ApiError(504), ApiError(429)]
    call = failing(errors)

    with pytest.raises(ApiError) as caught:
        await call_with_retry(call, policy(sleeps))

    assert caught.value.code == 429  # type: ignore[attr-defined]
    assert call.calls["n"] == 3  # type: ignore[attr-defined]
    assert sleeps.calls == [2.0, 4.0]


async def test_a_permanent_error_is_raised_at_once_without_waiting() -> None:
    sleeps = Sleeps()
    call = failing([ApiError(400)])

    with pytest.raises(ApiError):
        await call_with_retry(call, policy(sleeps))

    assert call.calls["n"] == 1 and sleeps.calls == []  # type: ignore[attr-defined]


async def test_the_total_wait_budget_stops_retrying_early() -> None:
    sleeps = Sleeps()
    call = failing([ApiError(503), ApiError(503), ApiError(503)])

    with pytest.raises(ApiError):
        await call_with_retry(call, policy(sleeps, attempts=5, max_total_wait_s=5.0))

    assert sleeps.calls == [2.0]  # lần chờ thứ hai (4 s) vượt ngân sách 5 s
    assert call.calls["n"] == 2  # type: ignore[attr-defined]


async def test_no_retry_policy_calls_once() -> None:
    call = failing([ApiError(503)])

    with pytest.raises(ApiError):
        await call_with_retry(call, NO_RETRY)

    assert call.calls["n"] == 1  # type: ignore[attr-defined]


async def test_each_retry_is_logged_with_the_run_tag(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.agent.llm_retry")
    call = failing([ApiError(503)])

    await call_with_retry(call, policy(Sleeps()), tag="[run 42] ", stage="planner")

    assert "[run 42] LLM planner lỗi tạm thời ApiError/503, thử lại lần 1 sau 2.0 s" in caplog.text


# ---- cấu hình ----
def test_settings_defaults_build_the_documented_policy() -> None:
    names = (
        "llm_retry_attempts",
        "llm_retry_base_seconds",
        "llm_retry_max_delay_seconds",
        "llm_retry_max_total_seconds",
    )
    defaults = {name: Settings.model_fields[name].default for name in names}
    assert tuple(defaults.values()) == (3, 2.0, 10.0, 20.0)
    built = RetryPolicy.from_settings(make_settings(**defaults))
    assert (built.attempts, built.base_delay_s, built.max_delay_s, built.max_total_wait_s) == (
        3,
        2.0,
        10.0,
        20.0,
    )


def test_test_settings_never_retry() -> None:
    assert RetryPolicy.from_settings(make_settings()).attempts == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_retry_attempts", 0),
        ("llm_retry_attempts", 7),
        ("llm_retry_base_seconds", -1),
        ("llm_retry_max_delay_seconds", 121),
        ("llm_retry_max_total_seconds", float("inf")),
    ],
)
def test_out_of_range_retry_settings_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})
