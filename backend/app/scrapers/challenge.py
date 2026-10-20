"""Phát hiện trang chặn bot / captcha (docs/06 §4).

Chỉ phát hiện và báo; không bao giờ giải captcha. Pipeline quyết định `NEEDS_HUMAN` (mock-shop) hoặc
`BLOCKED` (trang thật).
"""

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
    "turnstile",  # widget Cloudflare Turnstile (div `cf-turnstile`)
    "verify you are human",
    "xác minh bạn không phải robot",
)


def _fold(text: str) -> str:
    """Đưa về NFC + chữ thường để khớp không phân biệt hoa/thường và dạng Unicode của tiếng Việt."""
    return unicodedata.normalize("NFC", text).casefold()


# Thân `<script>`/`<style>` nội tuyến và chú thích HTML (biến môi trường Next.js, JSON-LD, mã theo
# dõi, `.grecaptcha-badge{visibility:hidden}`...) hay chứa chữ như `NEXT_PUBLIC_CAPTCHA_KEY` trên
# trang bình thường mà người dùng không thấy. Chỉ bỏ phần thân; thẻ mở (kể cả `src`) vẫn được giữ
# nên widget reCAPTCHA/hCaptcha thật (div, iframe, `<script src=...>`) vẫn bị phát hiện. Phần
# không có điểm kết thì giữ nguyên để không bỏ sót. Duyệt bằng `str.find` (tuyến tính): regex lười
# gặp hàng nghìn thẻ không đóng sẽ chạy bậc hai và treo event loop.
_NAME_CHARS = frozenset("_-")


def _strip_bodies(folded: str, opener: str, closer: str, *, tag: bool) -> str:
    """Bỏ phần giữa `opener...>` (hoặc hết `opener` nếu không phải thẻ) và `closer`."""
    parts: list[str] = []
    pos = 0
    while True:
        start = folded.find(opener, pos)
        if start < 0:
            break
        after = start + len(opener)
        next_char = folded[after] if after < len(folded) else ""
        if tag and (next_char.isalnum() or next_char in _NAME_CHARS):
            parts.append(folded[pos:after])  # `<scripts…`: không phải thẻ này, tìm tiếp
            pos = after
            continue
        keep_end = after
        if tag:
            open_end = folded.find(">", after)
            if open_end < 0:
                break
            keep_end = open_end + 1
        close = folded.find(closer, keep_end)
        if close < 0:
            break
        parts.append(folded[pos:keep_end])
        pos = close
    parts.append(folded[pos:])
    return "".join(parts)


def _captcha_text(text: str) -> str:
    """Thân trang đã bỏ script/style nội tuyến và chú thích, dùng để tìm từ khóa captcha."""
    folded = _fold(text)
    folded = _strip_bodies(folded, "<script", "</script", tag=True)
    folded = _strip_bodies(folded, "<style", "</style", tag=True)
    return _strip_bodies(folded, "<!--", "-->", tag=False)


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
