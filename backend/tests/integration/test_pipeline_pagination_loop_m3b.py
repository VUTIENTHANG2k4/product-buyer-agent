"""M3b/T2.7g: vòng lặp phân trang kết thúc PARTIAL với thông điệp riêng, không phải "giới hạn"."""

from collections.abc import Callable

from sqlmodel import Session

from app.domain.enums import Category, ScrapeStatus, ScrapeTrigger, SiteKey
from tests.integration.test_pipeline import (
    LAPTOP,
    Clock,
    ScriptedFetcher,
    card,
    clock,  # noqa: F401 - fixture
    factory,  # noqa: F401 - fixture
    listing,
    page,
    pipeline,
)


def with_next_link(html: str, href: str) -> str:
    return html.replace("</body>", f'<a rel="next" href="{href}">Trang sau</a></body>')


async def test_a_pagination_loop_ends_partial_with_its_own_message(
    db_session: Session,
    factory: Callable[[], Session],  # noqa: F811
    clock: Clock,  # noqa: F811
) -> None:
    fetcher = ScriptedFetcher(
        {LAPTOP: page(with_next_link(listing([card("a", "Laptop Acer Mock A")]), "/c/laptop"))}
    )

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test
    )

    assert result.status is ScrapeStatus.PARTIAL
    assert result.error_message is not None
    assert "Phân trang lặp lại" in result.error_message
    assert "giới hạn số trang" not in result.error_message
    assert (result.pages_fetched, result.offers_upserted) == (1, 1)


async def test_hitting_the_page_limit_keeps_the_page_limit_message(
    db_session: Session,
    factory: Callable[[], Session],  # noqa: F811
    clock: Clock,  # noqa: F811
) -> None:
    first = with_next_link(listing([card("a", "Laptop Acer Mock A")]), "/c/laptop?page=2")
    fetcher = ScriptedFetcher({LAPTOP: page(first)})

    result = await pipeline(factory, fetcher, clock).run(
        SiteKey.mockshop, Category.laptop, ScrapeTrigger.test, max_pages=1
    )

    assert result.status is ScrapeStatus.PARTIAL
    assert result.error_message is not None
    assert "giới hạn số trang" in result.error_message
    assert "Phân trang lặp lại" not in result.error_message
