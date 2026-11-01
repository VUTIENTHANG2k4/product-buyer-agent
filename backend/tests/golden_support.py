"""Hỗ trợ golden test (tests/unit/golden/*.yaml): nạp ca và lấy tiêu đề/thông số thật từ fixture.

Mỗi ca ghi `site`, `fixture` (trang danh sách hoặc chi tiết FPT Shop đã lưu) và `title`; thông số
thô (`raw_specs`) lấy lại từ fixture lúc chạy, không chép vào YAML, nên test cũng kiểm được rằng
tiêu đề golden đúng là tiêu đề có thật trong fixture.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.domain.enums import Category, SiteKey
from app.scrapers.base import BaseScraper
from app.scrapers.sites.anphat import AnPhatScraper
from app.scrapers.sites.fptshop import FptShopScraper
from app.scrapers.sites.gearvn import GearVNScraper

TESTS_DIR = Path(__file__).resolve().parent
GOLDEN_DIR = TESTS_DIR / "unit" / "golden"

_SCRAPERS: dict[SiteKey, type[BaseScraper]] = {
    SiteKey.gearvn: GearVNScraper,
    SiteKey.anphat: AnPhatScraper,
    SiteKey.fptshop: FptShopScraper,
}


# Trang chi tiết FPT Shop được lưu theo slug; nhóm nhận ra qua tiền tố của slug.
_FPT_PREFIX: dict[Category, str] = {
    Category.laptop: "detail_laptop-",
    Category.mouse: "detail_chuot-",
    Category.keyboard: "detail_ban-phim-",
    Category.headset: "detail_tai-nghe-",
}


@dataclass(frozen=True)
class GoldenCase:
    id: str
    site: SiteKey
    fixture: str  # đường dẫn tương đối so với tests/
    title: str
    expect: dict[str, Any]
    detail_fixture: str | None = None  # trang chi tiết cho `raw_specs` (GearVN, An Phát)
    note: str | None = None


def scraper_for(site: SiteKey) -> BaseScraper:
    """Scraper không có fetcher: chỉ dùng cho hàm parse (thuần), không bao giờ gọi mạng."""
    return _SCRAPERS[site](None)  # type: ignore[arg-type]


def load_cases(name: str) -> list[GoldenCase]:
    """Nạp `tests/unit/golden/<name>.yaml`."""
    raw = yaml.safe_load((GOLDEN_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return [
        GoldenCase(
            id=item["id"],
            site=SiteKey(item["site"]),
            fixture=item["fixture"],
            title=item["title"],
            expect=item.get("expect", {}),
            detail_fixture=item.get("detail_fixture"),
            note=item.get("note"),
        )
        for item in raw
    ]


def fixture_items(site: SiteKey, fixture: str, category: Category) -> dict[str, dict[str, str]]:
    """{tiêu đề: raw_specs} của mọi sản phẩm trong một fixture."""
    return {title: dict(raw) for title, raw in _parsed_items(site, fixture, category)}


@cache
def _parsed_items(
    site: SiteKey, fixture: str, category: Category
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    html = (TESTS_DIR / fixture).read_text(encoding="utf-8")
    scraper = scraper_for(site)
    if isinstance(scraper, FptShopScraper):
        item = scraper.parse_product(html, "https://fptshop.com.vn/x", category)
        return ((item.title, tuple(item.raw_specs.items())),)
    page = scraper.parse_listing(html, category, scraper.listing_url(category, 1))
    return tuple((item.title, tuple(item.raw_specs.items())) for item in page.items)


def real_titles(site: SiteKey, category: Category) -> dict[str, dict[str, str]]:
    """{tiêu đề: raw_specs} của mọi sản phẩm của (site, nhóm) trong các fixture đã lưu."""
    folder = TESTS_DIR / "fixtures" / site.value
    pattern = "detail_*.html" if site is SiteKey.fptshop else f"listing_{category.value}_*.html"
    found: dict[str, dict[str, str]] = {}
    for path in sorted(folder.glob(pattern)):
        if site is SiteKey.fptshop and _FPT_PREFIX[category] not in path.name:
            continue
        found.update(fixture_items(site, f"fixtures/{site.value}/{path.name}", category))
    return found


@dataclass(frozen=True)
class PairSide:
    site: SiteKey
    title: str
    synthetic_from_title: str | None = None  # có khi `title` là bản viết lại từ tiêu đề thật
    synthetic_from_site: SiteKey | None = None


@dataclass(frozen=True)
class GoldenPair:
    id: str
    category: Category
    expect: str  # "merge" | "separate"
    why: str
    a: PairSide
    b: PairSide


def _pair_side(raw: dict[str, Any]) -> PairSide:
    source = raw.get("synthetic_from")
    return PairSide(
        site=SiteKey(raw["site"]),
        title=raw["title"],
        synthetic_from_title=source["title"] if source else None,
        synthetic_from_site=SiteKey(source["site"]) if source else None,
    )


def load_pairs() -> list[GoldenPair]:
    """Nạp `tests/unit/golden/pairs.yaml`."""
    raw = yaml.safe_load((GOLDEN_DIR / "pairs.yaml").read_text(encoding="utf-8"))
    return [
        GoldenPair(
            id=item["id"],
            category=Category(item["category"]),
            expect=item["expect"],
            why=item["why"],
            a=_pair_side(item["a"]),
            b=_pair_side(item["b"]),
        )
        for item in raw
    ]


def case_raw_specs(case: GoldenCase, category: Category) -> dict[str, str]:
    """`raw_specs` của ca: từ trang chi tiết nếu có, nếu không thì từ chính fixture của ca."""
    if case.detail_fixture is not None:
        html = (TESTS_DIR / case.detail_fixture).read_text(encoding="utf-8")
        scraper = scraper_for(case.site)
        return dict(scraper.parse_detail(html, "https://example.invalid/x").raw_specs)
    return fixture_items(case.site, case.fixture, category)[case.title]
