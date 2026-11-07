"""Fixture Nguyễn Kim (X1.1, docs/06 §8): kích thước, không dữ liệu cá nhân, robots.txt cho URL."""

import json
import re
from pathlib import Path

import pytest

from app.scrapers.http.robots import parse_robots

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nguyenkim"
USER_AGENT = "ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: test@example.com)"
BASE = "https://www.nguyenkim.com"
# Mã số thuế của doanh nghiệp (JSON-LD `Organization` / chân trang), không phải số cá nhân.
SHOP_NUMBERS = {"0302286281"}
# Chuỗi cấu hình chip (`Mali-G615@1.047GHz`) khớp nhầm mẫu email.
NOT_EMAILS = {"Mali-G615@1.047GHz"}

HTML_FIXTURES = sorted(FIXTURE_DIR.glob("*.html"))
TEXT_FIXTURES = [*HTML_FIXTURES, FIXTURE_DIR / "robots.txt"]
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def test_fixture_set_has_two_listing_pages_and_a_detail_page() -> None:
    names = {path.name for path in HTML_FIXTURES}
    assert {"listing_dien-thoai_p1.html", "listing_dien-thoai_p2.html"} <= names
    assert any(name.startswith("detail_dien-thoai-") for name in names)
    assert (FIXTURE_DIR / "robots.txt").is_file()


@pytest.mark.parametrize("path", TEXT_FIXTURES, ids=lambda path: path.name)
def test_fixture_is_smaller_than_500_kb_and_valid_utf8(path: Path) -> None:
    assert path.stat().st_size < 500 * 1024
    assert "�" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_has_no_personal_contact_data(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    phones = set(re.findall(r"(?<!\d)0\d{9,10}(?!\d)", text))
    assert emails <= NOT_EMAILS
    assert phones <= SHOP_NUMBERS


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_keeps_no_scripts_except_json_ld_and_next_data(path: Path) -> None:
    scripts = re.findall(r"<script\b[^>]*>", path.read_text(encoding="utf-8"))
    assert scripts
    assert all("application/ld+json" in s or "__NEXT_DATA__" in s for s in scripts)


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_has_no_review_section(path: Path) -> None:
    """Đánh giá (có tên người) bị loại khỏi `__NEXT_DATA__`; JSON-LD không còn tên tác giả."""
    text = path.read_text(encoding="utf-8")
    match = NEXT_DATA.search(text)
    assert match is not None
    page_props = json.loads(match.group(1))["props"]["pageProps"]
    assert set(page_props) <= {"pageDetail", "pageType"}
    assert "reviews" not in page_props["pageDetail"].get("data", {})
    authors = re.findall(r'"author":\s*\{[^}]*\}', text)
    assert all('"name": "[đã ẩn]"' in author or '"name":"[đã ẩn]"' in author for author in authors)


@pytest.mark.parametrize("name", ["listing_dien-thoai_p1.html", "listing_dien-thoai_p2.html"])
def test_listing_fixture_embeds_a_page_of_phones_with_prices(name: str) -> None:
    text = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    match = NEXT_DATA.search(text)
    assert match is not None
    detail = json.loads(match.group(1))["props"]["pageProps"]["pageDetail"]
    assert detail["limit"] == 25
    assert len(detail["data"]) == 25
    assert detail["pages"] >= 2
    assert all(isinstance(item["price"], int) and item["price"] > 0 for item in detail["data"])
    assert all(item["name"]["vi"] and item["slugs"]["value"]["vi"] for item in detail["data"])


@pytest.fixture(scope="module")
def robots_text() -> str:
    return (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/dien-thoai.c",
        f"{BASE}/dien-thoai.c?page=2",
        f"{BASE}/dien-thoai-di-dong-oppo-cph2859-8gb-256gb-reno16-f-5g-8gb-256gb-trang-CPH28598GB256GB",
    ],
)
def test_saved_robots_txt_allows_urls_the_scraper_uses(robots_text: str, url: str) -> None:
    assert parse_robots(robots_text, USER_AGENT).allowed(url)


@pytest.mark.parametrize(
    "url",
    [f"{BASE}/checkout", f"{BASE}/account/", f"{BASE}/cart/", f"{BASE}/login", f"{BASE}/compare"],
)
def test_saved_robots_txt_blocks_checkout_account_and_cart(robots_text: str, url: str) -> None:
    assert not parse_robots(robots_text, USER_AGENT).allowed(url)
