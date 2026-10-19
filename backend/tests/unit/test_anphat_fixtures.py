"""Fixture An Phát (T4.3, docs/06 §8): kích thước, không dữ liệu cá nhân, robots.txt cho URL."""

import re
from pathlib import Path

import pytest

from app.scrapers.http.robots import parse_robots

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "anphat"
USER_AGENT = "ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: test@example.com)"
BASE = "https://www.anphatpc.com.vn"
SHOP_TAX_ID = "0108940873"  # mã số thuế của doanh nghiệp, không phải số cá nhân

HTML_FIXTURES = sorted(FIXTURE_DIR.glob("*.html"))
TEXT_FIXTURES = [*HTML_FIXTURES, FIXTURE_DIR / "robots.txt"]


def test_fixture_set_covers_docs_06_section_8_minimum() -> None:
    names = {path.name for path in HTML_FIXTURES}
    for category in ("laptop", "mouse", "keyboard", "headset"):
        assert f"listing_{category}_p1.html" in names
    assert "listing_mouse_p12.html" in names  # trang cuối: ít hơn 30 sản phẩm
    assert "listing_mouse_p13.html" in names  # vượt trang cuối: 0 sản phẩm
    details = {name for name in names if name.startswith("detail_")}
    for prefix in ("detail_laptop-", "detail_chuot-", "detail_ban-phim-", "detail_tai-nghe-"):
        assert any(name.startswith(prefix) for name in details), prefix
    assert (FIXTURE_DIR / "robots.txt").is_file()


@pytest.mark.parametrize("path", TEXT_FIXTURES, ids=lambda path: path.name)
def test_fixture_is_smaller_than_500_kb_and_valid_utf8(path: Path) -> None:
    assert path.stat().st_size < 500 * 1024
    assert "�" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_has_no_personal_contact_data(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text) == []
    assert set(re.findall(r"(?<!\d)0\d{9,10}(?!\d)", text)) <= {SHOP_TAX_ID}
    # Số di động viết có dấu chấm ("0936.021.377") của quầy tư vấn/showroom cũng đã được che.
    assert re.findall(r"(?<![\d.])0\d{2,3}[. ]\d{3}[. ]\d{3,4}(?![\d.])", text) == []
    assert "Mr.Kiên" not in text


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_keeps_no_scripts_except_json_ld(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", text)
    assert all('type="application/ld+json"' in script for script in scripts)


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_hides_reviewer_names_in_json_ld(path: Path) -> None:
    authors = re.findall(r'"author":\s*\{[^}]*\}', path.read_text(encoding="utf-8"))
    assert all('"name": "[đã ẩn]"' in author for author in authors)


@pytest.fixture(scope="module")
def robots_text() -> str:
    return (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/may-tinh-xach-tay-laptop.html",
        f"{BASE}/may-tinh-xach-tay-laptop.html?page=2",
        f"{BASE}/chuot-may-tinh_dm1291.html?page=12",
        f"{BASE}/ban-phim-may-tinh_dm1027.html?page=3",
        f"{BASE}/tai-nghe_dm1180.html?page=4",
        f"{BASE}/chuot-logitech-g102-lightsync.html",
        f"{BASE}/sitemap.xml",
    ],
)
def test_saved_robots_txt_allows_urls_the_scraper_uses(robots_text: str, url: str) -> None:
    assert parse_robots(robots_text, USER_AGENT).allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/admin/",
        f"{BASE}/ajax/check_user.php",
        f"{BASE}/cart",
        f"{BASE}/cart/checkout",
        f"{BASE}/tim-kiem?q=chuot",  # nhóm `*` thứ hai ở cuối file: Disallow: /tim
    ],
)
def test_saved_robots_txt_blocks_admin_ajax_cart_and_search(robots_text: str, url: str) -> None:
    assert not parse_robots(robots_text, USER_AGENT).allowed(url)


def test_both_wildcard_groups_apply_and_crawl_delay_is_five_seconds(robots_text: str) -> None:
    rules = parse_robots(robots_text, USER_AGENT)
    assert rules.crawl_delay == 5.0
    assert not rules.allowed(f"{BASE}/ajax/x")  # nhóm `*` đầu
    assert not rules.allowed(f"{BASE}/tim")  # nhóm `*` sau
