"""M3b/T2.7g: `crawl_category` đánh dấu trang cuối khi liên kết "trang sau" quay về URL đã tải."""

from tests.unit.test_base_scraper import LAPTOP, PAGE2, crawl, make, response


async def test_a_next_link_back_to_an_earlier_page_flags_the_last_yielded_page() -> None:
    scraper, fetcher = make({LAPTOP: response(1, PAGE2), PAGE2: response(1, LAPTOP, url=PAGE2)})

    pages = await crawl(scraper, max_pages=10)

    assert [page.pagination_loop for page in pages] == [False, True]
    assert pages[-1].has_next is True
    assert fetcher.requested == [LAPTOP, PAGE2]


async def test_a_page_pointing_at_itself_is_a_loop_from_the_first_page() -> None:
    scraper, _ = make({LAPTOP: response(2, LAPTOP)})

    pages = await crawl(scraper, max_pages=10)

    assert len(pages) == 1
    assert pages[0].pagination_loop is True
    assert len(pages[0].items) == 2  # trang vẫn được trả để pipeline lưu


async def test_the_page_limit_is_not_reported_as_a_loop() -> None:
    scraper, _ = make(
        {LAPTOP: response(1, PAGE2), PAGE2: response(1, f"{LAPTOP}?page=3", url=PAGE2)}
    )

    pages = await crawl(scraper, max_pages=2)

    assert [page.pagination_loop for page in pages] == [False, False]
    assert pages[-1].has_next is True


async def test_the_last_real_page_is_not_a_loop() -> None:
    scraper, _ = make({LAPTOP: response(1, PAGE2), PAGE2: response(1, None, url=PAGE2)})

    pages = await crawl(scraper, max_pages=10)

    assert [(page.has_next, page.pagination_loop) for page in pages] == [
        (True, False),
        (False, False),
    ]
