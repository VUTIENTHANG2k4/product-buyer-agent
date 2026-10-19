"""DTO miền: dữ liệu đi qua ranh giới module (docs/04 §6).

Tiền là `int` VND. URL phải là http/https hợp lệ; việc bỏ tham số theo dõi (utm_*, fbclid…)
do `normalize/url.clean_url` làm trước khi dựng DTO (T2.5), không làm ở đây.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, model_validator

from app.domain.enums import Category, ChallengeKind, PriceType, SiteKey, StockStatus

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Strict: không nhận bool hay chuỗi "27490000" cho số nguyên (parser phải chuẩn hóa trước).
Vnd = Annotated[int, Field(ge=0, strict=True)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class ListingItem(BaseModel):
    """Đầu ra parser trang danh sách: một thẻ sản phẩm."""

    site: SiteKey
    url: HttpUrl
    title: NonEmptyStr
    price: Vnd | None = None  # None nếu không đọc được hoặc bị che
    list_price: Vnd | None = None
    price_type: PriceType = PriceType.unknown
    stock_status: StockStatus = StockStatus.unknown
    image_url: HttpUrl | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0, strict=True)
    site_sku: str | None = None
    raw_specs: dict[str, str] = Field(default_factory=dict)  # nhãn → giá trị thô trên thẻ
    category_hint: Category = Category.other


class ListingPage(BaseModel):
    """Một trang danh sách đã parse."""

    items: list[ListingItem] = Field(default_factory=list)
    has_next: bool = False
    next_url: HttpUrl | None = None


class ProductDetail(BaseModel):
    """Đầu ra parser trang chi tiết."""

    url: HttpUrl
    raw_specs: dict[str, str] = Field(default_factory=dict)
    model_code_hint: str | None = None  # MPN/SKU từ JSON-LD nếu có
    brand_hint: str | None = None


class Challenge(BaseModel):
    """Dấu hiệu trang chặn bot hoặc đòi captcha (docs/06 §4); lưu JSON vào `ScrapeRun.challenge`.

    `prompt` và `token` chỉ có ở mock-shop (luồng nhập đáp án HITL); trang thật chỉ có `kind`.
    """

    kind: ChallengeKind
    site: SiteKey
    url: HttpUrl
    prompt: str | None = None
    image_url: HttpUrl | None = None
    token: str | None = None


class SpecFilter(BaseModel):
    """Một điều kiện lọc trên trường trong khung specs.

    - `contains`: trường kiểu list chứa `value`.
    - `contains_any`: trường kiểu list chứa ít nhất một phần tử của `value` (list).
    - `in`: trường vô hướng thuộc `value` (list).
    """

    field: NonEmptyStr  # ví dụ "gpu_rank", "ram_gb"
    op: Literal["eq", "gte", "lte", "contains", "contains_any", "in"]
    # bool đứng đầu để `True` không bị ép thành `1` (trường bool như `is_gaming`).
    value: bool | int | FiniteFloat | str | list[str]

    @model_validator(mode="after")
    def _value_matches_op(self) -> Self:
        is_list = isinstance(self.value, list)
        is_number = isinstance(self.value, int | float) and not isinstance(self.value, bool)
        if self.op in ("in", "contains_any") and not is_list:
            raise ValueError(f"op '{self.op}' requires a list value")
        if self.op in ("gte", "lte") and not is_number:
            raise ValueError(f"op '{self.op}' requires a numeric value")
        if self.op in ("eq", "contains") and is_list:
            raise ValueError(f"op '{self.op}' requires a scalar value")
        return self


class QueryIntent(BaseModel):
    """Đầu ra planner: ý định mua sắm có cấu trúc."""

    category: Category | None = None
    tier: Literal[1, 2] = 1
    keywords: list[str] = Field(default_factory=list)
    price_min: Vnd | None = None
    price_max: Vnd | None = None
    brands: list[str] = Field(default_factory=list)
    sites: list[SiteKey] = Field(default_factory=list)  # rỗng = mọi trang
    spec_filters: list[SpecFilter] = Field(default_factory=list)
    sort: Literal["relevance", "price_asc", "price_desc", "rating_desc"] = "relevance"
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    needs_clarification: bool = False
    clarification_question: str | None = None
    plan_steps: list[str] = Field(default_factory=list)  # hiển thị cho người dùng

    @model_validator(mode="after")
    def _price_range_is_ordered(self) -> Self:
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min must not be greater than price_max")
        return self
