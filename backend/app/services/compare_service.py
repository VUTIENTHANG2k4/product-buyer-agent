"""So sánh 2–5 sản phẩm (docs/05 §3 tool `compare_products`, docs/07 `POST /compare`)."""

import json
from typing import Any

from sqlmodel import Session

from app.domain.catalog import Comparison
from app.domain.clock import utc_now
from app.domain.errors import ProductNotFound, ValidationFailed
from app.services.catalog_service import CatalogService
from app.services.views import Clock

MIN_COMPARE = 2
MAX_COMPARE = 5


def _fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class CompareService:
    def __init__(self, session: Session, *, now: Clock = utc_now) -> None:
        self._catalog = CatalogService(session, now=now)

    def compare(self, product_ids: list[int]) -> Comparison:
        """Thông số đầy đủ, các trường khác nhau và sản phẩm rẻ nhất.

        `product_ids` phải có 2..5 id khác nhau; id không tồn tại → `ProductNotFound` (kèm danh
        sách id thiếu). Sản phẩm rẻ nhất xét theo giá thấp nhất còn mua được; hòa thì id nhỏ hơn.
        """
        if not MIN_COMPARE <= len(product_ids) <= MAX_COMPARE:
            raise ValidationFailed(
                f"Cần {MIN_COMPARE}–{MAX_COMPARE} sản phẩm để so sánh",
                details={"count": len(product_ids)},
            )
        if len(set(product_ids)) != len(product_ids):
            raise ValidationFailed("Danh sách sản phẩm so sánh có id trùng")
        products = self._catalog.get_many(product_ids)
        found = {product.product_id for product in products}
        missing = [pid for pid in product_ids if pid not in found]
        if missing:
            raise ProductNotFound(details={"product_ids": missing})

        names: list[str] = []
        for product in products:
            names.extend(name for name in product.specs if name not in names)
        differing = [
            name
            for name in names
            if len({_fingerprint(product.specs.get(name)) for product in products}) > 1
        ]
        priced = [product for product in products if product.min_price is not None]
        cheapest = min(
            priced, key=lambda product: (product.min_price or 0, product.product_id), default=None
        )
        return Comparison(
            products=products,
            differing_fields=differing,
            cheapest_product_id=None if cheapest is None else cheapest.product_id,
        )
