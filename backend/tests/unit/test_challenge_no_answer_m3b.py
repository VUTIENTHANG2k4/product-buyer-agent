"""M3b/T2.7f: `BaseScraper.detect_challenge` mặc định chỉ báo có challenge, không trích đáp án.

Dự án không bao giờ giải captcha (docs/02 §3): chỉ mock-shop ghi đè `detect_challenge` để lấy
đề bài và `token` cho người dùng nhập đáp án.
"""

from typing import ClassVar

import pytest

from app.domain.dto import ListingPage
from app.domain.enums import Category, ChallengeKind, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.types import FetchResponse
from app.scrapers.sites.gearvn import GearVNScraper
from app.scrapers.sites.mockshop import MockShopScraper
from tests.fakes import FakeFetcher

CAPTCHA_PAGE = (
    '<html><body><div id="captcha" data-token="SECRET-TOKEN-123">Nhập mã: ANSWER-ABC123</div>'
    '<img src="/captcha.png" alt="ANSWER-ABC123"><form action="/captcha" method="post">'
    '<input type="hidden" name="token" value="SECRET-TOKEN-123"></form></body></html>'
)


class PlainScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.gearvn,
        base_url="https://shop.example",
        min_delay_s=5.0,
        categories={Category.laptop: "https://shop.example/c/laptop"},
    )

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        return ListingPage()


def response(text: str, status: int = 200) -> FetchResponse:
    return FetchResponse(
        url="https://shop.example/c/laptop",
        final_url="https://shop.example/c/laptop",
        status=status,
        text=text,
    )


@pytest.mark.parametrize("scraper_cls", [PlainScraper, GearVNScraper])
def test_default_detector_reports_a_captcha_without_prompt_token_or_image(
    scraper_cls: type[BaseScraper],
) -> None:
    challenge = scraper_cls(FakeFetcher({})).detect_challenge(response(CAPTCHA_PAGE))

    assert challenge is not None
    assert challenge.kind is ChallengeKind.captcha
    assert (challenge.prompt, challenge.token, challenge.image_url) == (None, None, None)
    assert "ANSWER-ABC123" not in challenge.model_dump_json()
    assert "SECRET-TOKEN-123" not in challenge.model_dump_json()


@pytest.mark.parametrize("status", [403, 429])
def test_default_detector_status_challenges_carry_no_page_content(status: int) -> None:
    challenge = PlainScraper(FakeFetcher({})).detect_challenge(response(CAPTCHA_PAGE, status))

    assert challenge is not None
    assert (challenge.prompt, challenge.token, challenge.image_url) == (None, None, None)


def test_default_scraper_has_no_answer_form() -> None:
    challenge = PlainScraper(FakeFetcher({})).detect_challenge(response(CAPTCHA_PAGE))
    assert challenge is not None

    with pytest.raises(NotImplementedError):
        PlainScraper(FakeFetcher({})).challenge_submission(challenge, "ANSWER-ABC123")


def test_only_the_mock_shop_extracts_the_prompt_and_token() -> None:
    challenge = MockShopScraper(FakeFetcher({})).detect_challenge(response(CAPTCHA_PAGE))

    assert challenge is not None
    assert challenge.token == "SECRET-TOKEN-123"
    assert challenge.prompt is not None
