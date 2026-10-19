"""Phát hiện trang chặn bot / captcha (docs/06 §4).

Chỉ phát hiện và báo; không bao giờ giải captcha. Pipeline quyết định `NEEDS_HUMAN` (mock-shop) hoặc
`BLOCKED` (trang thật).
"""

import re
import unicodedata
from collections.abc import Mapping

from app.domain.dto import Challenge
from app.domain.enums import ChallengeKind, SiteKey
from app.scrapers.http.types import FetchResponse

_CAPTCHA_MARKERS = (
    "captcha",
    "cf-challenge",
    "g-recaptcha",
    "hcaptcha",
    "verify you are human",
    "xác minh bạn không phải robot",
)


def _fold(text: str) -> str:
    """Đưa về NFC + chữ thường để khớp không phân biệt hoa/thường và dạng Unicode của tiếng Việt."""
    return unicodedata.normalize("NFC", text).casefold()


# Thân `<script>` nội tuyến (biến môi trường Next.js, JSON-LD, mã theo dõi...) hay chứa chữ như
# `NEXT_PUBLIC_CAPTCHA_KEY` trên trang bình thường. Chỉ bỏ phần thân; thẻ mở (kể cả `src`) vẫn
# được giữ nên widget reCAPTCHA/hCaptcha thật (div, iframe, `<script src=...>`) vẫn bị phát hiện.
# Thẻ `<script>` không đóng thì không khớp, giữ nguyên để không bỏ sót.
_SCRIPT_BODY = re.compile(r"(<script\b[^>]*>).*?(</script\s*>)", re.IGNORECASE | re.DOTALL)


def _captcha_text(text: str) -> str:
    """Thân trang đã bỏ nội dung script nội tuyến, dùng để tìm từ khóa captcha."""
    return _fold(_SCRIPT_BODY.sub(r"\1\2", text))


_FOLDED_MARKERS = tuple(_fold(marker) for marker in _CAPTCHA_MARKERS)
# Trang chờ của Cloudflare (thường kèm 503). Chỉ xét khi máy chủ là Cloudflare và mã là 5xx để
# không báo nhầm trang bình thường có cụm "just a moment". Không dùng "challenge-platform" trần:
# Cloudflare chèn `/cdn-cgi/challenge-platform/.../main.js` cả vào trang bình thường và trang lỗi
# của máy chủ gốc đi qua nó.
_CLOUDFLARE_INTERSTITIAL = (
    "just a moment",
    "attention required",
    "chl_page",
    "cf-browser-verification",
)


def is_blocking_error_response(status: int, headers: Mapping[str, str], text: str) -> bool:
    """5xx là trang challenge của CDN (Cloudflare…) chứ không phải lỗi máy chủ thật.

    Dấu hiệu: header `cf-mitigated: challenge`, từ khóa captcha trong thân, hoặc trang chờ của
    Cloudflare. Gửi lại trang như vậy chỉ thêm tải nên Fetcher trả ngay để scraper báo challenge.
    """
    if status < 500:
        return False
    lowered = {name.lower(): value.lower() for name, value in headers.items()}
    if lowered.get("cf-mitigated") == "challenge":
        return True
    if any(marker in _captcha_text(text) for marker in _FOLDED_MARKERS):
        return True
    body = _fold(text)
    return "cloudflare" in lowered.get("server", "") and any(
        marker in body for marker in _CLOUDFLARE_INTERSTITIAL
    )


class ChallengeDetected(Exception):
    """Trang yêu cầu challenge hoặc chặn truy cập; pipeline bắt và đổi trạng thái lượt thu thập."""

    def __init__(self, challenge: Challenge) -> None:
        super().__init__(f"{challenge.kind} at {challenge.url}")
        self.challenge = challenge


def _build(kind: ChallengeKind, site: SiteKey, url: str) -> Challenge:
    return Challenge.model_validate({"kind": kind, "site": site, "url": url})


def detect_challenge(resp: FetchResponse, site: SiteKey) -> Challenge | None:
    """Trả `Challenge` nếu phản hồi là 403, 429 hoặc chứa dấu hiệu captcha; ngược lại `None`.

    Mã trạng thái được xét trước từ khóa (403 có thân chứa "captcha" vẫn là `http_403`). Mã 429
    là kết quả cuối của Fetcher, tức đã hết lượt chờ `Retry-After`. 5xx của trang challenge CDN
    (`is_blocking_error_response`) là `captcha`.
    """
    if resp.status == 403:
        return _build(ChallengeKind.http_403, site, resp.final_url)
    if resp.status == 429:
        return _build(ChallengeKind.http_429, site, resp.final_url)
    if is_blocking_error_response(resp.status, resp.headers, resp.text):
        return _build(ChallengeKind.captcha, site, resp.final_url)
    if any(marker in _captcha_text(resp.text) for marker in _FOLDED_MARKERS):
        return _build(ChallengeKind.captcha, site, resp.final_url)
    return None


def robots_block_challenge(site: SiteKey, robots_url: str, status: int) -> Challenge:
    """robots.txt bị chặn (403, 429 hoặc trang challenge 5xx của CDN): `BLOCKED`, nghỉ 24 giờ.

    Luôn là `http_403`/`http_429`, không bao giờ `captcha`: robots.txt không có form nhập đáp án
    nên mock-shop cũng không được rơi vào `NEEDS_HUMAN`.
    """
    kind = ChallengeKind.http_429 if status == 429 else ChallengeKind.http_403
    return _build(kind, site, robots_url)


def soft_block_challenge(site: SiteKey, url: str) -> Challenge:
    """Nghi bị chặn mềm: trang 1 trả 200 nhưng 0 sản phẩm trong khi lượt trước có sản phẩm."""
    return _build(ChallengeKind.soft_block, site, url)
