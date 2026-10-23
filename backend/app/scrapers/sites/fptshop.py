"""Scraper của FPT Shop (docs/06 §6, docs/sources/fptshop.md).

Trang danh mục chỉ có ~25 sản phẩm trong HTML tĩnh (phần còn lại nạp bằng nút "Xem thêm" qua API) và
`?page=N` bị bỏ qua, nên không duyệt bằng phân trang. `crawl_category` lấy URL sản phẩm từ sitemap
(khai báo trong robots.txt) rồi tải từng trang chi tiết, đọc JSON-LD `Product`. Mỗi "trang" là một
lô `BATCH_SIZE` sản phẩm; `ListingItem` đã có thông số nên pipeline không tải chi tiết lần nữa.

`parse_*` và các hàm sitemap là hàm thuần. Giá flash sale theo suất không lưu: dùng giá công khai
trong JSON-LD (docs/sources/fptshop.md mục 5).
"""

import logging
import re
import unicodedata
from collections.abc import AsyncIterator, Sequence
from html import unescape
from typing import Any, ClassVar
from urllib.parse import SplitResult, urljoin, urlsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.domain.dto import ListingItem, ListingPage, ProductDetail
from app.domain.enums import Category, PriceType, SiteKey
from app.normalize.price import parse_price
from app.normalize.url import clean_url
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.challenge import ChallengeDetected, soft_block_challenge
from app.scrapers.http.errors import (
    FetchFailed,
    HttpStatusError,
    RedirectError,
    ResponseTooLarge,
    RobotsBlocked,
    RobotsDisallowed,
)
from app.scrapers.parsing import (
    json_ld_objects,
    node_text,
    schema_offer,
    schema_price,
    schema_stock,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://fptshop.com.vn"
SITEMAP_INDEX_URL = f"{_BASE_URL}/sitemap.xml"
BATCH_SIZE = 20  # sản phẩm mỗi "trang" của crawl_category
MAX_COUNT = 2**31 - 1  # cột `rating_count` là INTEGER (4 byte)
MAX_CONSECUTIVE_ERRORS = 3  # tải lỗi liên tiếp (5xx, quá lớn...) thì dừng lượt

_LAPTOP_SITEMAP_PATH = "/products/sitemap-may-tinh-xach-tay.xml"
# Phụ kiện chia nhiều sitemap (`sitemap-phu-kien.xml`, `-1`, `-2`...); `-gia-dung` là đồ gia dụng.
_ACCESSORY_SITEMAP = re.compile(r"^/products/sitemap-phu-kien(?:-\d+)?\.xml$")
# Phụ kiện đều ở `/phu-kien/<slug>`: nhóm suy ra từ tiền tố slug (docs/sources/fptshop.md mục 3).
_ACCESSORY_PREFIX: dict[Category, str] = {
    Category.mouse: "chuot-",
    Category.keyboard: "ban-phim-",
    Category.headset: "tai-nghe-",
}
# Một lượng từ `[^<]*` rồi `.strip()`: hai lượng từ cùng ăn khoảng trắng sẽ backtrack bậc ba trên
# `<loc>` không đóng. CDATA dùng `[^\]]*` để không quét quá điểm kết.
_LOC = re.compile(r"<loc>(?:\s*<!\[CDATA\[([^\]]*)\]\]>\s*|([^<]*))</loc>", re.IGNORECASE)
_PRICE_TEXT = re.compile(r"^\d{1,3}(?:\.\d{3})+đ$")
_HTTP_URL = TypeAdapter(HttpUrl)


# ---- sitemap (hàm thuần) ----------------------------------------------------------------------
def parse_sitemap_locs(xml: str) -> list[str]:
    """Các `<loc>` của sitemap hoặc chỉ mục sitemap, theo thứ tự (không gồm `image:loc`)."""
    locs: list[str] = []
    for match in _LOC.finditer(xml):
        cdata, plain = match.groups()
        loc = cdata.strip() if cdata is not None else unescape(plain or "").strip()
        if loc:
            locs.append(loc)
    return locs


def _split(url: str) -> SplitResult | None:
    """`urlsplit` không ném lỗi: `<loc>` sai dạng (`https://[host`) chỉ bị bỏ qua."""
    try:
        return urlsplit(url)
    except ValueError:
        return None


def _same_site(url: str) -> bool:
    parts = _split(url)
    return (
        parts is not None
        and parts.scheme == "https"
        and parts.netloc.lower() == urlsplit(_BASE_URL).netloc
    )


def select_sitemaps(category: Category, index_locs: Sequence[str]) -> list[str]:
    """Sitemap sản phẩm của `category` trong chỉ mục; chỉ nhận URL cùng máy chủ."""
    chosen: list[str] = []
    for loc in index_locs:
        if not _same_site(loc):
            continue
        path = urlsplit(loc).path  # `_same_site` đã chắc `urlsplit(loc)` không lỗi
        if category is Category.laptop:
            matches = path == _LAPTOP_SITEMAP_PATH
        else:
            matches = category in _ACCESSORY_PREFIX and _ACCESSORY_SITEMAP.match(path) is not None
        if matches and loc not in chosen:
            chosen.append(loc)
    return chosen


def select_product_urls(category: Category, locs: Sequence[str]) -> list[str]:
    """URL trang sản phẩm của `category` (bỏ trùng, giữ thứ tự sitemap)."""
    seen: set[str] = set()
    urls: list[str] = []
    for loc in locs:
        parts = _split(loc)
        if parts is None or not _same_site(loc) or parts.query or parts.fragment:
            continue  # URL có tham số có thể bị robots.txt chặn (`Disallow: /*t=`)
        segments = [part for part in parts.path.split("/") if part]
        if len(segments) != 2:
            continue
        section, slug = segments
        if category is Category.laptop:
            wanted = section == "may-tinh-xach-tay"
        else:
            prefix = _ACCESSORY_PREFIX.get(category)
            wanted = prefix is not None and section == "phu-kien" and slug.startswith(prefix)
        if not wanted:
            continue
        try:
            url = clean_url(loc)
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


# ---- trang sản phẩm (hàm thuần) ---------------------------------------------------------------
def _clean(text: str) -> str:
    """NFC, bỏ ký tự NUL (PostgreSQL không lưu được) và khoảng trắng hai đầu."""
    return unicodedata.normalize("NFC", text.replace("\x00", "")).strip()


def _product(tree: LexborHTMLParser) -> dict[str, Any] | None:
    for obj in json_ld_objects(tree):
        kind = obj.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
            return obj
    return None


def _price_fields(tree: LexborHTMLParser, product: dict[str, Any]) -> dict[str, Any]:
    """Giá bán, giá gốc gạch ngang, loại giá và tồn kho của một trang sản phẩm."""
    offer = schema_offer(product)
    price = schema_price(offer.get("price"))
    list_price = _struck_price(tree, price) if price is not None else None
    price_type = PriceType.unknown
    if price is not None:
        price_type = PriceType.sale if list_price is not None else PriceType.regular
    return {
        "price": price,
        "list_price": list_price,
        "price_type": price_type,
        "stock_status": schema_stock(offer),
    }


def _struck_price(tree: LexborHTMLParser, price: int) -> int | None:
    """Giá gốc gạch ngang nằm cạnh giá bán công khai; khối flash sale (giá khác) không tính."""
    shown = f"{price:,}".replace(",", ".") + "đ"
    for node in tree.css(".line-through"):
        text = node_text(node)
        if not _PRICE_TEXT.match(text):
            continue
        struck = parse_price(text)
        if struck is None or struck <= price:
            continue
        block: LexborNode | None = node.parent
        for _ in range(3):  # giá bán và giá gốc là hai phần tử gần nhau trong cùng khối
            if block is None:
                break
            if any(node_text(leaf) == shown for leaf in block.css("p, span, div")):
                return struck
            block = block.parent
    return None


def _image_url(page_url: str, product: dict[str, Any]) -> str | None:
    image = product.get("image")
    candidates = image if isinstance(image, list) else [image]
    for candidate in candidates:
        src = candidate.get("url") if isinstance(candidate, dict) else candidate
        if isinstance(src, str) and src.strip() and not src.startswith("data:"):
            try:
                return str(_HTTP_URL.validate_python(urljoin(page_url, src.strip())))
            except (ValueError, ValidationError):
                continue
    return None


def _rating(product: dict[str, Any]) -> tuple[float | None, int | None]:
    block = product.get("aggregateRating")
    if not isinstance(block, dict):
        return None, None
    value, count = block.get("ratingValue"), block.get("reviewCount")
    rating: float | None = None
    if not isinstance(value, bool) and isinstance(value, int | float | str):
        try:
            number = float(value)
        except ValueError:
            number = -1.0
        rating = number if 0 <= number <= 5 else None
    votes: int | None = None
    if isinstance(count, str) and count.isascii() and count.isdecimal() and len(count) <= 10:
        count = int(count)
    if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= MAX_COUNT:
        votes = count
    return rating, votes


def _additional_properties(product: dict[str, Any]) -> dict[str, str]:
    """`additionalProperty[{name, value}]` → `nhãn → giá trị`; bỏ giá trị rỗng, nối nhãn lặp."""
    specs: dict[str, str] = {}
    properties = product.get("additionalProperty")
    for prop in properties if isinstance(properties, list) else []:
        if not isinstance(prop, dict):
            continue
        name, value = prop.get("name"), prop.get("value")
        if not isinstance(name, str) or isinstance(value, bool):
            continue
        if not isinstance(value, str | int | float):
            continue
        label, text = _clean(name), _clean(str(value))
        if not label or not text:
            continue
        values = specs[label].split("; ") if label in specs else []
        if text not in values:
            specs[label] = "; ".join([*values, text])
    return specs


def _brand_name(product: dict[str, Any]) -> str | None:
    brand = product.get("brand")
    name = brand.get("name") if isinstance(brand, dict) else brand
    return name.strip() if isinstance(name, str) and name.strip() else None


class FptShopScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.fptshop,
        base_url=_BASE_URL,
        min_delay_s=5.0,
        # URL danh mục chỉ để tham chiếu (không phân trang được); sản phẩm lấy từ sitemap.
        categories={
            Category.laptop: f"{_BASE_URL}/may-tinh-xach-tay",
            Category.mouse: f"{_BASE_URL}/phu-kien/chuot",
            Category.keyboard: f"{_BASE_URL}/phu-kien/ban-phim",
            Category.headset: f"{_BASE_URL}/phu-kien/tai-nghe",
        },
    )

    # ---- parse (hàm thuần) ----
    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        raise NotImplementedError("FPT Shop has no parsable listing page; see crawl_category")

    def parse_product(self, html: str, url: str, category: Category) -> ListingItem:
        """Một trang sản phẩm → `ListingItem`; ném `ValueError` nếu thiếu JSON-LD `Product`/tên."""
        tree = LexborHTMLParser(html)
        product = _product(tree)
        if product is None:
            raise ValueError("product page without JSON-LD Product")
        page_url = clean_url(url)
        prices = _price_fields(tree, product)
        # Tên trong `h1` đầy đủ hơn JSON-LD (laptop có CPU/RAM/SSD/màn hình/GPU).
        name = product.get("name")
        title = _clean(node_text(tree.css_first("h1"))) or (
            _clean(name) if isinstance(name, str) else ""
        )
        sku = product.get("sku")
        rating, rating_count = _rating(product)
        return ListingItem.model_validate(
            {
                "site": SiteKey.fptshop,
                "url": page_url,
                "title": title,
                **prices,
                "image_url": _image_url(page_url, product),
                "rating": rating,
                "rating_count": rating_count,
                "site_sku": (_clean(sku) or None) if isinstance(sku, str) else None,
                "raw_specs": _additional_properties(product),
                "category_hint": category,
            }
        )

    def parse_detail(self, html: str, url: str) -> ProductDetail:
        tree = LexborHTMLParser(html)
        product = _product(tree) or {}
        return ProductDetail.model_validate(
            {
                "url": clean_url(url),
                **_price_fields(tree, product),
                "raw_specs": _additional_properties(product),
                # `mpn` = `sku` = mã nội bộ của FPT Shop, không phải mã hãng.
                "model_code_hint": None,
                "brand_hint": _brand_name(product),
            }
        )

    # ---- điều phối ----
    async def product_urls(self, category: Category) -> list[str]:
        """Tải chỉ mục sitemap rồi các sitemap của `category`; trả URL sản phẩm đã lọc."""
        if category not in self.config.categories:
            raise ValueError(f"{self.config.key} has no source for category {category}")
        index = await self._fetcher.get(SITEMAP_INDEX_URL)
        self._raise_if_challenge(index)
        urls: list[str] = []
        for sitemap_url in select_sitemaps(category, parse_sitemap_locs(index.text)):
            sitemap = await self._fetcher.get(sitemap_url)
            self._raise_if_challenge(sitemap)
            urls.extend(select_product_urls(category, parse_sitemap_locs(sitemap.text)))
        return list(dict.fromkeys(urls))

    async def crawl_category(
        self,
        category: Category,
        max_pages: int,
        *,
        start_page: int = 1,
        expect_items: bool = False,
    ) -> AsyncIterator[ListingPage]:
        """Mỗi "trang" là `BATCH_SIZE` sản phẩm đọc từ trang chi tiết (xem docstring module)."""
        if max_pages < 1 or start_page < 1:
            raise ValueError("max_pages and start_page must be >= 1")
        urls = await self.product_urls(category)
        batches = [urls[i : i + BATCH_SIZE] for i in range(0, len(urls), BATCH_SIZE)] or [[]]
        for page_no in range(start_page, min(max_pages, len(batches)) + 1):
            items: list[ListingItem] = []
            skipped = gone = 0
            errors = 0  # lỗi tải liên tiếp; một URL lỗi không làm mất cả lô
            for url in batches[page_no - 1]:
                try:
                    response = await self._fetcher.get(url)
                except RobotsBlocked:
                    raise  # robots.txt bị chặn cả trang: dừng lượt, không phải lỗi của một sản phẩm
                except (
                    HttpStatusError,
                    FetchFailed,
                    ResponseTooLarge,
                    RobotsDisallowed,
                    RedirectError,
                ) as error:
                    if isinstance(error, HttpStatusError) and error.status in (404, 410):
                        gone += 1  # đã gỡ nhưng còn trong sitemap: hết bán, không phải lỗi parse
                        continue
                    skipped += 1
                    errors += 1
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        raise
                    logger.warning("Bỏ qua sản phẩm tải lỗi (%s): %s", error, url)
                    continue
                errors = 0
                self._raise_if_challenge(response)
                try:
                    items.append(self.parse_product(response.text, response.final_url, category))
                except (ValueError, ValidationError):
                    skipped += 1
                    logger.warning("Bỏ qua trang sản phẩm không đọc được: %s", url)
            # Cả lô trống vì sản phẩm đã gỡ (sitemap cũ) không phải dấu hiệu bị chặn.
            if page_no == 1 and expect_items and not items and not gone:
                raise ChallengeDetected(soft_block_challenge(self.config.key, SITEMAP_INDEX_URL))
            yield ListingPage(
                items=items, has_next=page_no < len(batches), skipped=skipped, gone=gone
            )
