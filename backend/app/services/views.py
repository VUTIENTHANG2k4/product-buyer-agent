"""Hàm dựng DTO dùng chung cho các service (offer, sản phẩm, giá tốt nhất)."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from app.db.models import Offer, Product
from app.db.repositories import effective_price_of
from app.domain.catalog import OfferView, ProductFull
from app.domain.enums import Category, StockStatus
from app.domain.errors import ValidationFailed

MAX_KEY_SPECS: Final = 6

# Thông số hiển thị gọn trong bảng kết quả (thứ tự ưu tiên, tối đa `MAX_KEY_SPECS`).
KEY_SPEC_FIELDS: Final[Mapping[Category, tuple[str, ...]]] = MappingProxyType(
    {
        Category.laptop: (
            "cpu_model",
            "gpu_model",
            "ram_gb",
            "storage_gb",
            "screen_in",
            "refresh_hz",
        ),
        Category.mouse: ("connection", "dpi_max", "sensor", "buttons", "weight_g", "rgb"),
        Category.keyboard: (
            "connection",
            "switch_type",
            "switch_name",
            "form_factor",
            "hot_swap",
            "backlight",
        ),
        Category.headset: ("form", "connection", "has_mic", "anc", "surround_7_1", "driver_mm"),
    }
)

Clock = Callable[[], datetime]


def aware_now(clock: Clock) -> datetime:
    """Thời điểm hiện tại từ `clock`; giờ không có múi giờ bị từ chối (so sánh với UTC sẽ sai)."""
    moment = clock()
    if moment.tzinfo is None:
        raise ValidationFailed("Thời điểm hiện tại phải có múi giờ (UTC)")
    return moment


def to_offer_view(offer: Offer) -> OfferView:
    if offer.id is None:  # pragma: no cover - offer đọc từ CSDL luôn có id
        raise RuntimeError("offer has no id")
    return OfferView(
        offer_id=offer.id,
        site=offer.site,
        title=offer.title,
        url=offer.url,
        price=offer.price,
        list_price=offer.list_price,
        effective_price=effective_price_of(offer),
        price_type=offer.price_type,
        stock_status=offer.stock_status,
        rating=offer.rating,
        scraped_at=offer.scraped_at,
    )


def sellable(offers: Sequence[Offer], *, include_out_of_stock: bool = False) -> list[Offer]:
    """Offer còn mua được (bỏ `out_of_stock` trừ khi `include_out_of_stock`), rẻ nhất trước."""
    kept = [
        offer
        for offer in offers
        if offer.is_active
        and (include_out_of_stock or offer.stock_status != StockStatus.out_of_stock)
    ]
    return sorted(kept, key=lambda offer: (effective_price_of(offer), offer.id or 0))


def best_price(offers: Sequence[Offer]) -> int | None:
    """Giá hiệu lực thấp nhất trong các offer còn mua được (VND), None nếu không có."""
    best = sellable(offers)
    return effective_price_of(best[0]) if best else None


def key_specs(category: Category, specs: Mapping[str, Any]) -> dict[str, Any]:
    """Tối đa `MAX_KEY_SPECS` thông số nổi bật có giá trị (nhóm chưa khai báo: theo thứ tự lưu)."""
    names = KEY_SPEC_FIELDS.get(category) or tuple(specs)
    picked: dict[str, Any] = {}
    for name in names:
        value = specs.get(name)
        if value is None or value == []:
            continue
        picked[name] = value
        if len(picked) == MAX_KEY_SPECS:
            break
    return picked


def to_product_full(product: Product, offers: Sequence[Offer]) -> ProductFull:
    if product.id is None:  # pragma: no cover - sản phẩm đọc từ CSDL luôn có id
        raise RuntimeError("product has no id")
    active = sellable(offers, include_out_of_stock=True)
    buyable = sellable(offers)
    prices = [effective_price_of(offer) for offer in buyable]
    return ProductFull(
        product_id=product.id,
        name=product.canonical_name,
        brand=product.brand,
        category=product.category,
        model_code=product.model_code,
        specs=dict(product.specs),
        specs_confidence=product.specs_confidence,
        image_url=product.image_url,
        offers=[to_offer_view(offer) for offer in active],
        min_price=min(prices) if prices else None,
        max_price=max(prices) if prices else None,
    )
