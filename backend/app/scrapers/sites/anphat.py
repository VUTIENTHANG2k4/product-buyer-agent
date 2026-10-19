"""Scraper của An Phát Computer (docs/06 §6, docs/sources/anphat.md).

Khung của T4.3 để `scripts.fetch_page` lưu được fixture qua Fetcher; phần parse viết ở T4.4.
"""

import re
from dataclasses import replace
from typing import ClassVar

from app.domain.dto import Challenge, ListingPage
from app.domain.enums import Category, SiteKey
from app.scrapers.base import BaseScraper, SiteConfig
from app.scrapers.http.types import FetchResponse

_BASE_URL = "https://www.anphatpc.com.vn"
# Mọi trang của An Phát (kể cả trang sản phẩm bình thường và trang danh sách rỗng) chứa sẵn form
# đăng ký có ô captcha. Chỉ loại đúng các tên của form đó; bất kỳ chữ captcha nào khác vẫn bị coi
# là challenge (docs/sources/anphat.md mục 7).
_REGISTER_FORM_CAPTCHA = re.compile(
    r"register_captcha|check_user_captcha|captchaimg|/includes/captcha/captcha\.php",
    re.IGNORECASE,
)


class AnPhatScraper(BaseScraper):
    config: ClassVar[SiteConfig] = SiteConfig(
        key=SiteKey.anphat,
        base_url=_BASE_URL,
        min_delay_s=5.0,
        categories={
            Category.laptop: f"{_BASE_URL}/may-tinh-xach-tay-laptop.html",
            Category.mouse: f"{_BASE_URL}/chuot-may-tinh_dm1291.html",
            Category.keyboard: f"{_BASE_URL}/ban-phim-may-tinh_dm1027.html",
            Category.headset: f"{_BASE_URL}/tai-nghe_dm1180.html",
        },
    )

    def detect_challenge(self, resp: FetchResponse) -> Challenge | None:
        cleaned = replace(resp, text=_REGISTER_FORM_CAPTCHA.sub("", resp.text))
        return super().detect_challenge(cleaned)

    def parse_listing(self, html: str, category: Category, page_url: str) -> ListingPage:
        raise NotImplementedError("AnPhatScraper.parse_listing is written in T4.4")
