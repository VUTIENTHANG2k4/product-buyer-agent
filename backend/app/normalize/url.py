"""Làm sạch URL sản phẩm để dùng làm khóa tự nhiên của `Offer` (docs/04 §7)."""

import re
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

MAX_URL_LENGTH = 2000
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "srsltid"})
_TRACKING_PREFIXES = ("utm_",)
_DEFAULT_PORTS = {"http": 80, "https": 443}
# Ký tự được giữ nguyên trong chuỗi truy vấn; `%` giữ nguyên các `%XX` có sẵn.
_QUERY_SAFE = "%!$'()*+,;=:@/?[]-._~"
_PERCENT_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")


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


def _clean_query(query: str) -> str:
    """Bỏ tham số theo dõi, giữ nguyên mã hóa gốc của phần còn lại và sắp theo tên tham số.

    Không giải mã rồi mã hóa lại (`%20` không thành `+`); chỉ mã hóa `%XX` cho ký tự ngoài ASCII
    hoặc không an toàn, và `?a` thành `?a=`. Sắp ổn định theo tên nên `?a=1&b=2` và
    `?b=2&a=1` là một khóa, còn các giá trị của cùng một tham số giữ thứ tự xuất hiện.
    """
    kept: list[tuple[str, str]] = []
    for segment in query.split("&"):
        if not segment:
            continue
        name = segment.partition("=")[0]
        key = unquote_plus(name).lower()
        if key in _TRACKING_PARAMS or key.startswith(_TRACKING_PREFIXES):
            continue
        if "=" not in segment:
            segment += "="
        encoded = quote(segment, safe=_QUERY_SAFE)
        # `%c3%a9` và `%C3%A9` là một byte: viết hoa hex để không thành hai khóa.
        kept.append((name, _PERCENT_ESCAPE.sub(lambda match: match.group().upper(), encoded)))
    kept.sort(key=lambda pair: pair[0])
    return "&".join(segment for _, segment in kept)


def clean_url(url: str) -> str:
    """Bỏ `utm_*`, `fbclid`, `gclid`, `srsltid`, userinfo, fragment và cổng mặc định.

    Chuỗi truy vấn giữ mã hóa gốc và được sắp theo tên tham số (xem `_clean_query`). Host về chữ
    thường (IDN → punycode). Ném `ValueError` khi không phải URL http/https tuyệt
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
    cleaned = urlunsplit((parts.scheme.lower(), netloc, parts.path, _clean_query(parts.query), ""))
    if len(cleaned) > MAX_URL_LENGTH:
        raise ValueError(f"URL longer than {MAX_URL_LENGTH} characters")
    return cleaned


def scheme_twin(url: str) -> str:
    """Cùng URL nhưng đổi http ↔ https (đầu vào đã qua `clean_url`); scheme khác trả nguyên.

    URL có cổng riêng (`:8080`) trả nguyên: cổng mặc định đã bị `clean_url` bỏ, còn hai cổng
    tùy chọn của http và https là hai máy chủ khác nhau.
    """
    parts = urlsplit(url)
    twin = {"http": "https", "https": "http"}.get(parts.scheme)
    if twin is None or parts.port is not None:
        return url
    return urlunsplit(parts._replace(scheme=twin))
