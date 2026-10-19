"""Làm sạch URL sản phẩm để dùng làm khóa tự nhiên của `Offer` (docs/04 §7)."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2000
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "srsltid"})
_TRACKING_PREFIXES = ("utm_",)


def clean_url(url: str) -> str:
    """Bỏ `utm_*`, `fbclid`, `gclid`, `srsltid`, userinfo và fragment; giữ đường dẫn, tham số khác.

    Ném `ValueError` khi không phải URL http/https tuyệt đối, hoặc dài hơn `MAX_URL_LENGTH` ký tự
    (khóa UNIQUE của `offer.url` không nhận URL quá dài).
    """
    text = url.strip()
    if len(text) > MAX_URL_LENGTH:
        raise ValueError(f"URL longer than {MAX_URL_LENGTH} characters")
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an absolute http(s) URL: {text[:80]!r}")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"  # IPv6
    netloc = f"{host}:{parts.port}" if parts.port is not None else host
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    cleaned = urlunsplit((parts.scheme.lower(), netloc, parts.path, urlencode(query), ""))
    if len(cleaned) > MAX_URL_LENGTH:  # urlencode có thể nở ra (ký tự %xx)
        raise ValueError(f"URL longer than {MAX_URL_LENGTH} characters")
    return cleaned
