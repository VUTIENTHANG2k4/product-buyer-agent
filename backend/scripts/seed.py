"""Nạp dữ liệu hư cấu vào PostgreSQL (docs/09 §3, T1.5).

Chạy từ `backend/`: `uv run python -m scripts.seed --fixture dev|eval|e2e [--reset --yes]`
(`make seed FIXTURE=dev`). Dữ liệu gốc là JSON ở `tests/fixtures/seed/`:

- `<nhóm>.json`: `{"category": "laptop", "products": [...]}`, mỗi sản phẩm kèm các offer.
- `extras.json` (chỉ cho `dev`/`eval`): danh sách mua và cảnh báo giá mẫu.

Profile: `dev` và `eval` nạp toàn bộ (kèm danh sách mua, cảnh báo, lượt thu thập mẫu); `e2e` chỉ nạp
sản phẩm có `"e2e": true` và không có dữ liệu phụ (luồng E2E tự tạo).

Mọi sản phẩm/offer là hư cấu: tên có chữ "Mock", URL thuộc miền `.example`. Giá lịch sử đi qua
`record_snapshot` nên tuân luật thêm dòng của docs/04 §3. Chạy lại không nhân đôi dòng (khóa tự
nhiên là (nhóm, hãng, mã mẫu) và `offer.url`); offer đã có được ghi đè bằng giá trị trong fixture
(lịch sử giá chỉ thêm dòng khi đổi giá hoặc dòng cuối cũ hơn 24 giờ).
"""

import argparse
import io
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel

from app.config import get_settings
from app.db.engine import get_engine
from app.db.models import Product, utc_now
from app.db.repositories import (
    OfferRepository,
    OfferUpsert,
    PriceAlertRepository,
    PriceHistoryRepository,
    ProductRepository,
    ScrapeRunRepository,
    ShoppingListRepository,
)
from app.domain.dto import NonEmptyStr, Vnd
from app.domain.enums import (
    AlertChannel,
    Category,
    MatchMethod,
    PriceType,
    ScrapeStatus,
    ScrapeTrigger,
    SiteKey,
    StockStatus,
)
from app.normalize.specs import REQUIRED_FIELDS, SPEC_MODELS

logger = logging.getLogger("seed")

FixtureName = Literal["dev", "eval", "e2e"]

FIXTURE_DIR: Final = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "seed"
EXTRAS_FILE: Final = "extras.json"
HISTORY_DAYS: Final = 30
MOCK_MARK: Final = "Mock"
MOCK_HOST_SUFFIX: Final = ".example"
SCRAPE_RUN_DURATION: Final = timedelta(minutes=5)


class SeedDataError(ValueError):
    """Dữ liệu seed sai khung hoặc vi phạm quy ước hư cấu; thông điệp nói rõ mục lỗi."""


class HistoryPoint(BaseModel):
    """Một điểm đổi giá: từ `days_ago` ngày trước, giá là `price` (VND) cho đến điểm kế tiếp."""

    model_config = ConfigDict(extra="forbid")

    days_ago: int = Field(ge=1, le=HISTORY_DAYS, strict=True)
    price: Vnd


class SeedOffer(BaseModel):
    """Một offer hư cấu; `price` là giá hiện tại, `history` là các điểm đổi giá trước đó."""

    model_config = ConfigDict(extra="forbid")

    site: SiteKey
    url: HttpUrl
    title: NonEmptyStr
    price: Vnd
    list_price: Vnd | None = None
    price_type: PriceType = PriceType.regular
    stock_status: StockStatus = StockStatus.in_stock
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0, strict=True)
    history: list[HistoryPoint] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _fictional_host(cls, value: HttpUrl) -> HttpUrl:
        if not (value.host or "").endswith(MOCK_HOST_SUFFIX):
            raise ValueError(f"URL seed phải thuộc miền {MOCK_HOST_SUFFIX} (dữ liệu hư cấu)")
        return value

    @field_validator("title")
    @classmethod
    def _mock_title(cls, value: str) -> str:
        if MOCK_MARK not in value:
            raise ValueError(f"tên offer phải có chữ {MOCK_MARK!r}")
        return value

    @model_validator(mode="after")
    def _history_is_oldest_first(self) -> Self:
        days = [point.days_ago for point in self.history]
        if any(newer >= older for older, newer in zip(days, days[1:], strict=False)):
            raise ValueError("history phải xếp từ cũ đến mới (days_ago giảm dần, không trùng)")
        return self


class SeedProduct(BaseModel):
    """Một sản phẩm hư cấu; `specs` được kiểm bằng khung của nhóm khi nạp."""

    model_config = ConfigDict(extra="forbid")

    brand: NonEmptyStr
    model_code: NonEmptyStr
    canonical_name: NonEmptyStr
    specs: dict[str, Any]
    image_url: HttpUrl | None = None
    e2e: bool = False
    offers: list[SeedOffer] = Field(min_length=1)

    @field_validator("image_url")
    @classmethod
    def _fictional_image_host(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and not (value.host or "").endswith(MOCK_HOST_SUFFIX):
            raise ValueError(f"image_url phải thuộc miền {MOCK_HOST_SUFFIX} (dữ liệu hư cấu)")
        return value

    @field_validator("canonical_name")
    @classmethod
    def _mock_name(cls, value: str) -> str:
        if MOCK_MARK not in value:
            raise ValueError(f"tên sản phẩm phải có chữ {MOCK_MARK!r}")
        return value


class SeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    products: list[SeedProduct]


class SeedListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    brand: NonEmptyStr
    model_code: NonEmptyStr
    quantity: int = Field(default=1, ge=1, strict=True)
    note: str | None = None


class SeedAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    brand: NonEmptyStr
    model_code: NonEmptyStr
    target_price: int = Field(gt=0, strict=True)
    channel: AlertChannel = AlertChannel.email
    destination: NonEmptyStr


class SeedExtras(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shopping_list_name: NonEmptyStr
    shopping_list_items: list[SeedListItem] = Field(default_factory=list)
    alerts: list[SeedAlert] = Field(default_factory=list)


class CatalogProduct(NamedTuple):
    """Sản phẩm đã kiểm: `specs` là dict JSON sẵn sàng lưu (đã có `gpu_rank`, enum thành chuỗi)."""

    category: Category
    product: SeedProduct
    specs: dict[str, Any]


@dataclass(frozen=True)
class SeedSummary:
    products_created: int = 0
    products_existing: int = 0
    offers_created: int = 0
    offers_refreshed: int = 0
    history_rows: int = 0
    shopping_list_items: int = 0
    alerts: int = 0
    scrape_runs: int = 0


def normalize_specs(category: Category, raw: dict[str, Any]) -> dict[str, Any]:
    """Kiểm `raw` bằng khung specs của nhóm; trả dict JSON để lưu vào `product.specs`.

    Khung dùng `extra="ignore"` nên khóa gõ sai sẽ bị bỏ im lặng ở parser; với dữ liệu seed ta
    muốn lỗi to, nên từ chối khóa lạ và thiếu trường bắt buộc.
    """
    model_cls = SPEC_MODELS.get(category)
    if model_cls is None:
        raise SeedDataError(f"nhóm {category.value} không có khung thông số")
    unknown = sorted(set(raw) - set(model_cls.model_fields))
    if unknown:
        raise SeedDataError(f"specs có khóa lạ cho nhóm {category.value}: {unknown}")
    try:
        model = model_cls.model_validate(raw)
    except ValidationError as error:
        raise SeedDataError(f"specs sai khung của nhóm {category.value}: {error}") from error
    dumped = model.model_dump(mode="json", exclude_none=True)
    missing = [name for name in REQUIRED_FIELDS[category] if not dumped.get(name)]
    if missing:
        raise SeedDataError(f"specs thiếu trường bắt buộc của {category.value}: {missing}")
    return dumped


def load_catalog(fixtures_dir: Path = FIXTURE_DIR) -> list[CatalogProduct]:
    """Đọc mọi `<nhóm>.json` trong `fixtures_dir`; kiểm khung và tính duy nhất của khóa, URL."""
    paths = sorted(path for path in fixtures_dir.glob("*.json") if path.name != EXTRAS_FILE)
    if not paths:
        raise SeedDataError(f"không có file seed nào trong {fixtures_dir}")
    catalog: list[CatalogProduct] = []
    keys: set[tuple[Category, str, str]] = set()
    urls: set[str] = set()
    for path in paths:
        try:
            seed_file = SeedFile.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise SeedDataError(f"{path.name}: {error}") from error
        for product in seed_file.products:
            label = f"{path.name} / {product.model_code}"
            key = (seed_file.category, product.brand, product.model_code)
            if key in keys:
                raise SeedDataError(f"{label}: trùng (nhóm, hãng, mã mẫu)")
            keys.add(key)
            for offer in product.offers:
                if str(offer.url) in urls:
                    raise SeedDataError(f"{label}: trùng URL offer {offer.url}")
                urls.add(str(offer.url))
            try:
                specs = normalize_specs(seed_file.category, product.specs)
            except SeedDataError as error:
                raise SeedDataError(f"{label}: {error}") from error
            catalog.append(CatalogProduct(seed_file.category, product, specs))
    return catalog


def load_extras(fixtures_dir: Path = FIXTURE_DIR) -> SeedExtras | None:
    path = fixtures_dir / EXTRAS_FILE
    if not path.exists():
        return None
    try:
        return SeedExtras.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        raise SeedDataError(f"{EXTRAS_FILE}: {error}") from error


def reset_database(session: Session) -> None:
    """Xóa sạch mọi bảng ứng dụng và đặt lại id (`TRUNCATE … RESTART IDENTITY CASCADE`)."""
    quote = session.connection().dialect.identifier_preparer.quote
    tables = ", ".join(quote(table.name) for table in SQLModel.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def _price_points(offer: SeedOffer, *, existed: bool) -> list[tuple[int, int]]:
    """Các điểm (số ngày trước, giá) cần phát lại, cũ nhất trước, kết thúc ở hiện tại.

    Offer đã có chỉ làm mới ở hiện tại. Offer mới không khai báo `history` thì giữ giá phẳng từ
    `HISTORY_DAYS` ngày trước.
    """
    if existed:
        return [(0, offer.price)]
    opening = [(point.days_ago, point.price) for point in offer.history]
    return [*(opening or [(HISTORY_DAYS, offer.price)]), (0, offer.price)]


class _Seeder:
    def __init__(self, session: Session, moment: datetime) -> None:
        self.session = session
        self.moment = moment
        self.products = ProductRepository(session)
        self.offers = OfferRepository(session)
        self.history = PriceHistoryRepository(session)
        self.counts = {field.name: 0 for field in fields(SeedSummary)}

    def seed_product(self, item: CatalogProduct) -> Product:
        data = item.product
        product = self.products.find_by_model_key(item.category, data.brand, data.model_code)
        image_url = None if data.image_url is None else str(data.image_url)
        if product is None:
            product = self.products.add(
                Product(
                    category=item.category,
                    brand=data.brand,
                    model_code=data.model_code,
                    canonical_name=data.canonical_name,
                    specs=item.specs,
                    image_url=image_url,
                    created_at=self.moment - timedelta(days=HISTORY_DAYS),
                )
            )
            self.counts["products_created"] += 1
        else:
            product.canonical_name = data.canonical_name
            product.image_url = image_url
            self.products.update_specs(product, item.specs)
            self.counts["products_existing"] += 1
        assert product.id is not None
        for offer in data.offers:
            self._seed_offer(product.id, offer)
        return product

    def _seed_offer(self, product_id: int, offer: SeedOffer) -> None:
        url = str(offer.url)
        existed = self.offers.get_by_url(url) is not None
        for days_ago, price in _price_points(offer, existed=existed):
            at = self.moment - timedelta(days=days_ago)
            result = self.offers.upsert(
                OfferUpsert(
                    product_id=product_id,
                    site=offer.site,
                    url=url,
                    title=offer.title,
                    price=price,
                    list_price=offer.list_price,
                    price_type=offer.price_type,
                    stock_status=offer.stock_status,
                    rating=offer.rating,
                    rating_count=offer.rating_count,
                    match_method=MatchMethod.model_code,
                    match_score=1.0,
                ),
                now=at,
            )
            if self.history.record_snapshot(result.offer, now=at).added:
                self.counts["history_rows"] += 1
        self.counts["offers_refreshed" if existed else "offers_created"] += 1

    def seed_extras(self, extras: SeedExtras) -> None:
        lists = ShoppingListRepository(self.session)
        shopping_list = lists.get_by_name(extras.shopping_list_name) or lists.create(
            extras.shopping_list_name, now=self.moment
        )
        assert shopping_list.id is not None
        present = {item.product_id for item in lists.list_items(shopping_list.id)}
        for item in extras.shopping_list_items:
            product_id = self._product_id(item.category, item.brand, item.model_code)
            if product_id in present:
                continue
            lists.add_item(
                shopping_list.id,
                product_id,
                quantity=item.quantity,
                note=item.note,
                now=self.moment,
            )
            self.counts["shopping_list_items"] += 1
        alerts = PriceAlertRepository(self.session)
        for alert in extras.alerts:
            product_id = self._product_id(alert.category, alert.brand, alert.model_code)
            if alerts.find_live(product_id, alert.channel, alert.destination) is not None:
                continue
            alerts.create(
                product_id,
                alert.target_price,
                alert.channel,
                alert.destination,
                now=self.moment,
            )
            self.counts["alerts"] += 1

    def seed_scrape_runs(self, catalog: Sequence[CatalogProduct]) -> None:
        """Mỗi (trang, nhóm) có offer mà chưa có lượt SUCCEEDED thì thêm một lượt mẫu."""
        offers_per_pair: dict[tuple[SiteKey, Category], int] = {}
        for item in catalog:
            for offer in item.product.offers:
                pair = (offer.site, item.category)
                offers_per_pair[pair] = offers_per_pair.get(pair, 0) + 1
        runs = ScrapeRunRepository(self.session)
        for (site, category), count in sorted(offers_per_pair.items()):
            if runs.latest_succeeded(site, category) is not None:
                continue
            run = runs.create(
                site, category, ScrapeTrigger.test, now=self.moment - SCRAPE_RUN_DURATION
            )
            runs.update_counters(run, pages_fetched=1, items_parsed=count, offers_upserted=count)
            runs.set_status(run, ScrapeStatus.SUCCEEDED, now=self.moment)
            self.counts["scrape_runs"] += 1

    def _product_id(self, category: Category, brand: str, model_code: str) -> int:
        product = self.products.find_by_model_key(category, brand, model_code)
        if product is None or product.id is None:
            raise SeedDataError(f"extras tham chiếu sản phẩm không có trong seed: {model_code}")
        return product.id


def seed_database(
    session: Session,
    fixture: FixtureName,
    *,
    now: datetime | None = None,
    fixtures_dir: Path = FIXTURE_DIR,
) -> SeedSummary:
    """Nạp profile `fixture` vào `session` (flush, không commit); `now` là "hiện tại" (UTC)."""
    moment = now or utc_now()
    catalog = load_catalog(fixtures_dir)
    if fixture == "e2e":
        catalog = [item for item in catalog if item.product.e2e]
    seeder = _Seeder(session, moment)
    for item in catalog:
        seeder.seed_product(item)
    if fixture != "e2e":
        extras = load_extras(fixtures_dir)
        if extras is not None:
            seeder.seed_extras(extras)
        seeder.seed_scrape_runs(catalog)
    return SeedSummary(**seeder.counts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nạp dữ liệu hư cấu vào CSDL (docs/09 §3).")
    parser.add_argument("--fixture", choices=["dev", "eval", "e2e"], required=True)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="xóa sạch mọi bảng trước khi nạp (cho eval/e2e xác định); mặc định tắt",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="xác nhận --reset (bắt buộc đi kèm --reset vì lệnh xóa toàn bộ dữ liệu)",
    )
    args = parser.parse_args(argv)
    # Console Windows mặc định cp1252 làm hỏng dấu tiếng Việt trong log.
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.reset and not args.yes:
        logger.error("--reset xóa toàn bộ dữ liệu của CSDL: thêm --yes để xác nhận.")
        return 1

    engine = get_engine(get_settings().database_url.get_secret_value())
    try:
        with Session(engine) as session:
            if args.reset:
                logger.warning("Xóa toàn bộ dữ liệu của CSDL %r", engine.url.database)
                reset_database(session)
            summary = seed_database(session, args.fixture)
            session.commit()
    except SeedDataError as error:
        logger.error("Dữ liệu seed không hợp lệ: %s", error)
        return 1
    except OperationalError:
        logger.error("Không kết nối được CSDL. Chạy `make db-up` và kiểm tra DATABASE_URL.")
        return 1
    logger.info("Đã nạp seed %r vào %r: %s", args.fixture, engine.url.database, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
