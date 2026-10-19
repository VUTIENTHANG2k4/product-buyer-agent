"""Fixture FPT Shop (T4.1, docs/06 §8): kích thước, không dữ liệu cá nhân, robots.txt cho URL dùng."""

import re
from pathlib import Path

import pytest

from app.scrapers.http.robots import parse_robots

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "fptshop"
USER_AGENT = "ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: test@example.com)"
BASE = "https://fptshop.com.vn"
# Liên hệ của doanh nghiệp trong chân trang và JSON-LD `Organization` (không phải cá nhân).
SHOP_EMAILS = {"fptshop@fpt.com"}
SHOP_NUMBERS = {"0311609355", "02873023456"}  # mã số thuế và tổng đài

HTML_FIXTURES = sorted(FIXTURE_DIR.glob("*.html"))
XML_FIXTURES = sorted(FIXTURE_DIR.glob("*.xml"))
TEXT_FIXTURES = [*HTML_FIXTURES, *XML_FIXTURES, FIXTURE_DIR / "robots.txt"]


def test_fixture_set_covers_every_category_and_the_sitemaps() -> None:
    names = {path.name for path in HTML_FIXTURES}
    details = {name for name in names if name.startswith("detail_")}
    for prefix in ("detail_laptop-", "detail_chuot-", "detail_ban-phim-", "detail_tai-nghe-"):
        assert any(name.startswith(prefix) for name in details), prefix
    assert len([name for name in details if name.startswith("detail_laptop-")]) >= 2
    assert {"sitemap_index.xml", "sitemap_laptop.xml", "sitemap_phu-kien.xml"} <= {
        path.name for path in XML_FIXTURES
    }
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
    assert emails <= SHOP_EMAILS
    assert phones <= SHOP_NUMBERS


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_keeps_no_scripts_except_json_ld(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", text)
    assert scripts
    assert all('type="application/ld+json"' in script for script in scripts)


@pytest.mark.parametrize("path", HTML_FIXTURES, ids=lambda path: path.name)
def test_fixture_hides_reviewer_names_in_json_ld(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    authors = re.findall(r'"author":\s*\{[^}]*\}', text)
    assert all('"name": "[đã ẩn]"' in author for author in authors)


@pytest.fixture(scope="module")
def robots_text() -> str:
    return (FIXTURE_DIR / "robots.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/sitemap.xml",
        f"{BASE}/products/sitemap-may-tinh-xach-tay.xml",
        f"{BASE}/products/sitemap-phu-kien.xml",
        f"{BASE}/products/sitemap-phu-kien-2.xml",
        f"{BASE}/may-tinh-xach-tay/acer-aspire-lite-14-al14-44p-r0sp-r7-7730u",
        f"{BASE}/phu-kien/chuot-khong-day-elecom-m-ir07dr",
        f"{BASE}/phu-kien/ban-phim-co-khong-day-mchose-g75-pro-v2",
        f"{BASE}/phu-kien/tai-nghe-corsair-hs50-pro-stereo",
    ],
)
def test_saved_robots_txt_allows_urls_the_scraper_uses(robots_text: str, url: str) -> None:
    assert parse_robots(robots_text, USER_AGENT).allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/gio-hang/",
        f"{BASE}/ajax/products",
        f"{BASE}/tai-khoan/",
        f"{BASE}/dat-hang/",
        f"{BASE}/may-tinh-xach-tay?sort=gia-tang-dan",
        f"{BASE}/may-tinh-xach-tay?muc-gia=10-15-trieu",
        f"{BASE}/phu-kien/chuot?hang-san-xuat=logitech",
    ],
)
def test_saved_robots_txt_blocks_cart_account_api_and_filters(robots_text: str, url: str) -> None:
    assert not parse_robots(robots_text, USER_AGENT).allowed(url)
