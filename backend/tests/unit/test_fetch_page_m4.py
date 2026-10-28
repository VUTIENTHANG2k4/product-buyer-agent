"""QA M4: `scripts/fetch_page.py` với FptShopScraper và AnPhatScraper thật (respx, không mạng)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx

from app.config import Settings
from app.scrapers.http.fetcher import Fetcher
from scripts.fetch_page import EXIT_BLOCKED, EXIT_FAILED, EXIT_OK, main
from tests.unit.test_anphat_scraper import REGISTER_FORM


class _NoThrottle:
    """Thay khe dùng chung trong CSDL (T9.8): các test này không chạm CSDL."""

    async def reserve(self, domain: str, delay: float) -> float:
        return 0.0


@pytest.fixture(autouse=True)
def no_shared_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.fetch_page.DbDomainThrottle", lambda factory: _NoThrottle())


FPT = "https://fptshop.com.vn"
ANPHAT = "https://www.anphatpc.com.vn"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NEXT_ENV = (
    '<script>window["__ENV"] = {"NEXT_PUBLIC_CAPTCHA_KEY":"6Lf-key"}</script><h1>Chuột Elecom</h1>'
)


def _fetcher_without_site_delays(
    settings: Settings, *, raw_cache_dir: Path | None = None, shared_delay: object = None
) -> Fetcher:
    """Fetcher thật nhưng không có độ trễ 5 giây riêng của trang (test không được sleep thật)."""
    return Fetcher(settings, site_delays={}, raw_cache_dir=None)


@pytest.fixture(autouse=True)
def no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.scrapers.http.fetcher.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("scripts.fetch_page.build_fetcher", _fetcher_without_site_delays)


@pytest.fixture
def http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


def run(site: str, url: str, out: Path) -> int:
    return main(["--site", site, "--url", url, "--out", str(out), "--allow-online"])


def robots(site: str) -> str:
    """robots.txt đã lưu, bỏ `Crawl-delay` (test không sleep thật); luật Disallow giữ nguyên."""
    lines = (FIXTURES / site / "robots.txt").read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.lower().startswith("crawl-delay")]
    return chr(10).join(kept)


def test_fpt_page_with_a_captcha_key_in_an_inline_script_is_saved(
    http: respx.MockRouter, tmp_path: Path
) -> None:
    http.get(f"{FPT}/robots.txt").respond(200, text=robots("fptshop"))
    http.get(f"{FPT}/phu-kien/chuot-a").respond(200, text=NEXT_ENV)
    out = tmp_path / "p.html"

    assert run("fptshop", f"{FPT}/phu-kien/chuot-a", out) == EXIT_OK
    assert "<h1>Chuột Elecom</h1>" in out.read_text(encoding="utf-8")


def test_anphat_page_with_the_registration_form_is_saved_but_a_real_captcha_is_not(
    http: respx.MockRouter, tmp_path: Path
) -> None:
    http.get(f"{ANPHAT}/robots.txt").respond(200, text=robots("anphat"))
    http.get(f"{ANPHAT}/chuot-a.html").respond(200, text=f"<h1>Chuột</h1>{REGISTER_FORM}")
    http.get(f"{ANPHAT}/chuot-b.html").respond(
        200, text=f'{REGISTER_FORM}<div class="g-recaptcha"></div>'
    )
    saved, refused = tmp_path / "a.html", tmp_path / "b.html"

    assert run("anphat", f"{ANPHAT}/chuot-a.html", saved) == EXIT_OK
    assert run("anphat", f"{ANPHAT}/chuot-b.html", refused) == EXIT_BLOCKED
    assert saved.exists() and not refused.exists()


def test_anphat_5xx_with_the_registration_form_is_reported_as_blocked(
    http: respx.MockRouter, tmp_path: Path
) -> None:
    http.get(f"{ANPHAT}/robots.txt").respond(200, text=robots("anphat"))
    http.get(f"{ANPHAT}/chuot-a.html").respond(503, text=f"Lỗi{REGISTER_FORM}")
    out = tmp_path / "a.html"

    assert run("anphat", f"{ANPHAT}/chuot-a.html", out) == EXIT_BLOCKED
    assert not out.exists()


@pytest.mark.parametrize(
    ("site", "url"),
    [
        ("anphat", f"{ANPHAT}/ajax/products"),
        ("fptshop", f"{FPT}/ajax/products"),
        ("fptshop", f"{FPT}/phu-kien/chuot-a?utm_source=x"),
    ],
)
def test_urls_the_saved_robots_txt_disallows_are_never_requested(
    http: respx.MockRouter, tmp_path: Path, site: str, url: str
) -> None:
    base = ANPHAT if site == "anphat" else FPT
    http.get(f"{base}/robots.txt").respond(200, text=robots(site))
    page = http.get(url).respond(200, text="x")
    out = tmp_path / "x.html"

    assert run(site, url, out) == EXIT_FAILED
    assert page.call_count == 0 and not out.exists()


@pytest.mark.parametrize(
    ("site", "url"),
    [
        ("anphat", "https://www.anphatpc.com.vn@evil.example/x.html"),
        ("fptshop", "https://fptshop.com.vn.evil.example/x"),
        ("fptshop", "https://evil.example/https://fptshop.com.vn/x"),
        ("anphat", f"{FPT}/x"),
    ],
)
def test_urls_that_only_look_like_the_site_are_refused_without_any_request(
    http: respx.MockRouter, tmp_path: Path, site: str, url: str
) -> None:
    assert run(site, url, tmp_path / "x.html") == EXIT_FAILED
    assert http.calls.call_count == 0


def test_malformed_url_exits_with_a_failure_code_not_a_traceback(
    http: respx.MockRouter, tmp_path: Path
) -> None:
    assert run("fptshop", "https://[fptshop.com.vn/x", tmp_path / "x.html") == EXIT_FAILED
