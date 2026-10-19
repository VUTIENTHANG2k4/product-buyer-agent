"""Fixture GearVN (T3.1, docs/06 §8): kích thước, không dữ liệu cá nhân, robots.txt cho URL dùng."""

import re
from pathlib import Path

import pytest

from app.scrapers.http.robots import parse_robots

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gearvn"
USER_AGENT = "ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: test@example.com)"
BASE = "https://gearvn.com"
# Liên hệ của doanh nghiệp ở chân trang và JSON-LD `Organization` (không phải cá nhân).
SHOP_EMAILS = {"cskh@gearvn.com"}
SHOP_TAX_ID = "0316517394"

HTML_FIXTURES = sorted(FIXTURE_DIR.glob("*.html"))


def test_fixture_set_covers_docs_06_section_8_minimum() -> None:
    names = {path.name for path in HTML_FIXTURES}
    listing_categories = {"laptop", "mouse", "keyboard", "headset"}
    assert {f"listing_{category}_p1.html" for category in listing_categories} <= names
    assert "listing_mouse_p8.html" in names  # trang cuối: chỉ có rel=prev
    assert len([name for name in names if name.startswith("detail_")]) >= 2
    assert "search_chuot_razer.html" in names
    assert (FIXTURE_DIR / "robots.txt").is_file()


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_is_smaller_than_500_kb_and_valid_utf8(path: Path) -> None:
    assert path.stat().st_size < 500 * 1024
    assert "�" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_has_no_personal_contact_data(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    phones = set(re.findall(r"(?<!\d)0\d{9,10}(?!\d)", text))
    assert emails <= SHOP_EMAILS
    assert phones <= {SHOP_TAX_ID}


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_keeps_no_scripts_except_json_ld(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", text)
    assert all('type="application/ld+json"' in script for script in scripts)


@pytest.fixture(scope="module")
def robots_text() -> str:
    return (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/",
        f"{BASE}/collections/laptop",
        f"{BASE}/collections/laptop?page=2",
        f"{BASE}/collections/chuot-may-tinh?page=8",
        f"{BASE}/collections/ban-phim-may-tinh",
        f"{BASE}/collections/tai-nghe-may-tinh",
        f"{BASE}/products/laptop-acer-aspire-lite-15-al15-53p-56qh",
        f"{BASE}/search?q=chuot+razer",
    ],
)
def test_saved_robots_txt_allows_urls_the_scraper_uses(robots_text: str, url: str) -> None:
    assert parse_robots(robots_text, USER_AGENT).allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/api/products",
        f"{BASE}/gio-hang",
        f"{BASE}/thanh-toan",
        f"{BASE}/tai-khoan",
        f"{BASE}/design-system",
    ],
)
def test_saved_robots_txt_blocks_cart_checkout_account_and_api(robots_text: str, url: str) -> None:
    assert not parse_robots(robots_text, USER_AGENT).allowed(url)
