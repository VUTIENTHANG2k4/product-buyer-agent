"""Danh mục hư cấu của mock-shop: 60 sản phẩm trong `data.json` (tên có chữ "Mock")."""

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

DATA_FILE: Final = Path(__file__).with_name("data.json")
PAGE_SIZE: Final = 12
CATEGORIES: Final = ("laptop", "mouse", "keyboard", "headset")


class MockProduct(BaseModel):
    """Một sản phẩm của mock-shop. `price=None` nghĩa là "Liên hệ" (giá không công bố), VND."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    category: str
    name: str
    brand: str
    sku: str
    price: int | None = Field(default=None, strict=True, ge=0)
    list_price: int | None = Field(default=None, strict=True, ge=0)
    in_stock: bool = True
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int = Field(default=0, strict=True, ge=0)
    specs: dict[str, str]


@lru_cache
def load_catalog() -> tuple[MockProduct, ...]:
    """Đọc `data.json` một lần; ném lỗi nếu slug trùng hoặc nhóm lạ."""
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    products = tuple(MockProduct.model_validate(item) for item in raw["products"])
    slugs = [product.slug for product in products]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate slug in mock-shop data")
    unknown = {product.category for product in products} - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown categories in mock-shop data: {sorted(unknown)}")
    return products


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt: để tìm "chuot" ra "Chuột"."""
    nfd = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return "".join(char for char in nfd if not unicodedata.combining(char))


def search(products: tuple[MockProduct, ...], query: str, limit: int = 20) -> list[MockProduct]:
    """Sản phẩm có tên chứa mọi từ của `query` (không phân biệt hoa thường và dấu)."""
    words = fold(query).split()
    if not words:
        return []
    hits = [p for p in products if all(word in fold(p.name) for word in words)]
    return hits[:limit]
