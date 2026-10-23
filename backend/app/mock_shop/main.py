"""Mock-shop: trang bán lẻ giả lập (FastAPI, cổng 8100) cho test và demo (docs/06 §5, ADR-0006).

Dữ liệu hư cấu; có phân trang, robots.txt, tìm kiếm, captcha giả sau N request và chế độ lỗi
(`?fail=500|slow|empty`). Chỉ trang này có luồng nhập đáp án captcha; không bao giờ áp dụng cho
trang thật.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Literal
from urllib.parse import parse_qs

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from app.config import get_settings
from app.mock_shop import pages
from app.mock_shop.catalog import (
    CATEGORIES,
    PAGE_SIZE,
    MockProduct,
    load_catalog,
    load_search_catalog,
    search,
)
from app.mock_shop.state import PASS_TTL_SECONDS, ShopState

COOKIE_NAME = "mock_pass"
FailMode = Literal["500", "slow", "empty"]
ROBOTS_TXT = "User-agent: *\nDisallow: /admin\n"


def create_app(
    *,
    captcha_after: int | None = None,
    slow_seconds: float = 5.0,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    """Dựng một mock-shop độc lập (mỗi app một trạng thái); mặc định `MOCK_SHOP_CAPTCHA_AFTER`."""
    after = captcha_after if captcha_after is not None else get_settings().mock_shop_captcha_after
    state = ShopState(captcha_after=after, clock=clock)
    catalog = load_catalog()
    search_catalog = load_search_catalog()  # thêm nhóm tầng 2: chỉ cho /search và trang chi tiết
    app = FastAPI(
        title="Mock Shop (fictional data)", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.shop = state

    def base_url(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def html(content: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(content, status_code=status)

    def gate(request: Request) -> Response | None:
        """Captcha giả: chặn khi quá `captcha_after` request mà chưa có cookie hợp lệ."""
        challenge = state.requires_challenge(request.cookies.get(COOKIE_NAME))
        if challenge is not None:
            return html(pages.challenge_page(challenge.code, challenge.token))
        return None

    async def failure(fail: str | None) -> Response | None:
        """Chế độ lỗi cho test retry/timeout; `empty` do từng trang xử lý (200, không sản phẩm)."""
        if fail == "500":
            return PlainTextResponse("Mock Shop: lỗi giả lập", status_code=500)
        if fail == "slow":
            await asyncio.sleep(slow_seconds)
        return None

    @app.get("/robots.txt")
    def robots() -> PlainTextResponse:
        return PlainTextResponse(ROBOTS_TXT)

    @app.get("/c/{category}")
    async def category_page(
        request: Request,
        category: str,
        page: int = Query(default=1, ge=1, le=10_000),
        fail: FailMode | None = None,
    ) -> Response:
        if category not in CATEGORIES:
            return html(pages.not_found_page(f"Không có nhóm {category}"), 404)
        if (blocked := gate(request)) is not None:
            return blocked
        if (failed := await failure(fail)) is not None:
            return failed
        items = [product for product in catalog if product.category == category]
        window: list[MockProduct] = (
            [] if fail == "empty" else items[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        )
        has_next = fail != "empty" and page * PAGE_SIZE < len(items)
        extra = f"&fail={fail}" if fail else ""
        heading = f"Mock Shop - {pages.CATEGORY_TITLES[category]}"
        return html(
            pages.listing_page(
                base_url(request),
                heading,
                window,
                prev_href=f"/c/{category}?page={page - 1}{extra}" if page > 1 else None,
                next_href=f"/c/{category}?page={page + 1}{extra}" if has_next else None,
            )
        )

    @app.get("/p/{slug}")
    async def product_page(request: Request, slug: str, fail: FailMode | None = None) -> Response:
        if (blocked := gate(request)) is not None:
            return blocked
        if (failed := await failure(fail)) is not None:
            return failed
        product = next((item for item in search_catalog if item.slug == slug), None)
        if product is None:
            return html(pages.not_found_page("Không có sản phẩm này"), 404)
        return html(pages.detail_page(base_url(request), product))

    @app.get("/search")
    async def search_page(
        request: Request, q: str = Query(default="", max_length=200), fail: FailMode | None = None
    ) -> Response:
        if (blocked := gate(request)) is not None:
            return blocked
        if (failed := await failure(fail)) is not None:
            return failed
        hits = [] if fail == "empty" else search(search_catalog, q)
        heading = f"Kết quả cho: {q}" if q else "Tìm kiếm"
        return html(pages.listing_page(base_url(request), heading, hits))

    @app.post("/captcha")
    async def submit_captcha(request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
        token = form.get("token", [""])[0]
        answer = form.get("answer", [""])[0]
        cookie = state.solve(token, answer)
        if cookie is None:
            return html(pages.captcha_result_page(ok=False), 400)
        response = html(pages.captcha_result_page(ok=True))
        response.set_cookie(COOKIE_NAME, cookie, max_age=PASS_TTL_SECONDS, path="/", httponly=True)
        return response

    @app.get("/__control/reset")
    def reset() -> JSONResponse:
        """Chỉ cho test/demo: đặt lại bộ đếm, challenge và cookie đã xác minh."""
        state.reset()
        return JSONResponse({"status": "reset"})

    return app


app = create_app()
