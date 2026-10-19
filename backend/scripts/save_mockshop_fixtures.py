"""Sinh lại fixture HTML của mock-shop trong `tests/fixtures/mockshop/` (docs/06 §8).

Chạy từ `backend/`: `uv run python -m scripts.save_mockshop_fixtures`. Gọi mock-shop trong
tiến trình qua ASGI (không mở cổng, không mạng); chạy lại khi sửa `app/mock_shop/` hoặc
`data.json`. Test `test_mockshop_fixtures_match_the_live_app` báo khi fixture lệch mock-shop.
"""

import asyncio
import re
from pathlib import Path
from typing import Final

import httpx

from app.mock_shop.catalog import load_catalog
from app.mock_shop.main import create_app

FIXTURE_DIR: Final = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mockshop"
BASE: Final = "http://localhost:8100"
CAPTCHA_AFTER: Final = 2
FIXED_TOKEN: Final = "FIXTURETOKEN"
FIXED_CODE: Final = "AB3XY"


def _pick(category: str, *, priced: bool = True, in_stock: bool = True) -> str:
    """Slug đầu tiên của nhóm có (hoặc không có) giá và còn/hết hàng theo yêu cầu."""
    for product in load_catalog():
        if (
            product.category == category
            and (product.price is not None) == priced
            and product.in_stock == in_stock
        ):
            return product.slug
    raise LookupError(f"no {category} product with priced={priced}, in_stock={in_stock}")


def fixture_requests() -> dict[str, str]:
    """Tên file → đường dẫn cần gọi (mỗi file một lần gọi trên mock-shop mới)."""
    return {
        "listing_laptop_p1.html": "/c/laptop",
        "listing_laptop_p3.html": "/c/laptop?page=3",
        "listing_mouse_p1.html": "/c/mouse",
        "listing_empty.html": "/c/laptop?fail=empty",
        f"detail_{_pick('laptop')}.html": f"/p/{_pick('laptop')}",
        f"detail_{_pick('laptop', priced=False)}.html": f"/p/{_pick('laptop', priced=False)}",
        "search_chuot_razer.html": "/search?q=chuot+razer",
    }


def render() -> dict[str, str]:
    """Tên file → HTML hiện tại của mock-shop (kể cả trang captcha)."""

    async def run() -> dict[str, str]:
        out: dict[str, str] = {}
        for name, path in fixture_requests().items():
            app = create_app(captcha_after=1000)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE
            ) as client:
                out[name] = (await client.get(path)).text
        app = create_app(captcha_after=CAPTCHA_AFTER)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            for _ in range(CAPTCHA_AFTER + 1):
                page = (await client.get("/c/laptop")).text
        # Mã và token ngẫu nhiên mỗi lần chạy: cố định để fixture ổn định giữa các lần sinh.
        match = re.search(r'data-token="([^"]+)">([^<]+)</div>', page)
        if match is None:
            raise LookupError("mock-shop did not return a captcha page")
        token, code = match.groups()
        out["captcha.html"] = page.replace(token, FIXED_TOKEN).replace(
            f">{code}</div>", f">{FIXED_CODE}</div>"
        )
        return out

    return asyncio.run(run())


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, html in render().items():
        (FIXTURE_DIR / name).write_text(html, encoding="utf-8", newline="\n")
        print(f"wrote {name} ({len(html)} chars)")


if __name__ == "__main__":
    main()
