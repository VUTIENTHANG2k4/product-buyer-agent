"""Làm sạch URL sản phẩm để dùng làm khóa tự nhiên của `Offer` (docs/04 §7)."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2000
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "srsltid"})
_TRACKING_PREFIXES = ("utm_",)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def host_key(url: str) -> str:
    """`host[:port]` viết thường, bỏ cổng mặc định của scheme, dùng để so hai URL cùng máy chủ.

    Ném `ValueError` nếu không phải URL http/https tuyệt đối hoặc cổng không hợp lệ. Hai scheme
    http/https của cùng host coi như một.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise ValueError(f"not an absolute http(s) URL: {url.strip()[:80]!r}")
    host = parts.hostname.lower()
    try:
        host = host.encode("idna").decode("ascii")  # IDN → punycode, như HttpUrl của DTO
    except UnicodeError as exc:
        raise ValueError(f"invalid host in URL: {host[:80]!r}") from exc
    if ":" in host:
        host = f"[{host}]"  # IPv6
    port = parts.port  # ném ValueError nếu cổng không phải số hợp lệ
    return host if port is None or port == _DEFAULT_PORTS[scheme] else f"{host}:{port}"


def clean_url(url: str) -> str:
    """Bỏ `utm_*`, `fbclid`, `gclid`, `srsltid`, userinfo, fragment và cổng mặc định.

    Host về chữ thường (IDN → punycode). Ném `ValueError` khi không phải URL http/https tuyệt
    đối, có khoảng trắng/ký tự điều khiển, hoặc dài hơn `MAX_URL_LENGTH` ký tự (khóa UNIQUE của
    `offer.url` không nhận URL quá dài).
    """
    text = url.strip()
    if len(text) > MAX_URL_LENGTH:
        raise ValueError(f"URL longer than {MAX_URL_LENGTH} characters")
    if any(ord(char) <= 0x20 or 0x7F <= ord(char) <= 0x9F for char in text):
        raise ValueError("URL contains spaces or control characters")
    parts = urlsplit(text)
    netloc = host_key(text)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    cleaned = urlunsplit((parts.scheme.lower(), netloc, parts.path, urlencode(query), ""))
    if len(cleaned) > MAX_URL_LENGTH:  # urlencode có thể nở ra (ký tự %xx)
        raise ValueError(f"URL longer than {MAX_URL_LENGTH} characters")
    return cleaned
