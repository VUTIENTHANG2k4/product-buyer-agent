"""robots.txt: bộ phân tích riêng (hỗ trợ `*` và `$`) và bộ nhớ đệm 24 giờ mỗi domain (docs/06 §3).

`urllib.robotparser` chỉ khớp tiền tố, không hiểu `Disallow: /*?filter=` mà các trang bán lẻ dùng,
nên Fetcher tự phân tích theo RFC 9309: nhóm theo User-agent, quy tắc dài nhất thắng, hòa thì Allow.
"""

import asyncio
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.scrapers.http.errors import RobotsUnavailable

ROBOTS_TTL_SECONDS = 24 * 3600
MAX_ROBOTS_CHARS = 500 * 1024  # RFC 9309: bỏ phần vượt quá 500 KiB


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class RobotsRules:
    """Quy tắc đã chọn cho User-Agent của dự án."""

    rules: tuple[_Rule, ...] = ()
    crawl_delay: float | None = None  # giây
    disallow_all: bool = False

    def allowed(self, url: str) -> bool:
        """URL (kể cả chuỗi truy vấn) có được phép tải không."""
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        best: _Rule | None = None
        for rule in self.rules:
            if not rule.regex.match(target):
                continue
            if best is None:
                best = rule
                continue
            longer = len(rule.pattern) > len(best.pattern)
            tie_allow = len(rule.pattern) == len(best.pattern) and rule.allow
            if longer or tie_allow:
                best = rule
        return best is None or best.allow


ALLOW_ALL = RobotsRules()
DISALLOW_ALL = RobotsRules(disallow_all=True)


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(piece) for piece in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[_Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def parse_robots(text: str, user_agent: str) -> RobotsRules:
    """Quy tắc áp dụng cho `user_agent` (chuỗi User-Agent đầy đủ của dự án).

    Chọn nhóm có tên agent dài nhất nằm trong User-Agent; không có thì nhóm `*`; không có nhóm
    nào thì cho phép tất cả. Nhiều nhóm cùng tên được gộp.
    """
    groups: list[_Group] = []
    current: _Group | None = None
    reading_agents = False
    for raw in text[:MAX_ROBOTS_CHARS].splitlines():
        line = raw.split("#", 1)[0].strip()
        name, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = name.strip().lower(), value.strip()
        if key == "user-agent":
            if not reading_agents or current is None:
                current = _Group()
                groups.append(current)
            current.agents.append(value.lower())
            reading_agents = True
            continue
        reading_agents = False
        if current is None:
            continue
        if key in ("allow", "disallow"):
            if value:  # "Disallow:" rỗng nghĩa là không cấm gì
                current.rules.append(_Rule(key == "allow", value, _compile(value)))
        elif key == "crawl-delay":
            try:
                delay = float(value)
            except ValueError:
                continue
            if math.isfinite(delay) and delay >= 0:
                current.crawl_delay = delay

    ua = user_agent.lower()
    best_len = -1
    selected: list[_Group] = []
    for group in groups:
        for agent in group.agents:
            if agent == "*":
                matched = 0
            elif agent and agent in ua:
                matched = len(agent)
            else:
                continue
            if matched > best_len:
                best_len, selected = matched, [group]
            elif matched == best_len and group not in selected:
                selected.append(group)
    if not selected:
        return ALLOW_ALL
    delays = [g.crawl_delay for g in selected if g.crawl_delay is not None]
    return RobotsRules(
        rules=tuple(rule for g in selected for rule in g.rules),
        crawl_delay=max(delays) if delays else None,
    )


RobotsLoader = Callable[[str], Awaitable[tuple[int, str]]]
"""Tải `<origin>/robots.txt`, trả (mã trạng thái, nội dung); lỗi mạng ném `RobotsUnavailable`."""


class RobotsCache:
    """Quy tắc robots.txt theo origin, giữ `ttl` giây. Không tải được thì không lưu."""

    def __init__(
        self,
        loader: RobotsLoader,
        user_agent: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = ROBOTS_TTL_SECONDS,
    ) -> None:
        self._loader = loader
        self._user_agent = user_agent
        self._clock = clock
        self._ttl = ttl
        self._cache: dict[str, tuple[float, RobotsRules]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _fresh(self, origin: str) -> RobotsRules | None:
        cached = self._cache.get(origin)
        if cached is not None and self._clock() - cached[0] < self._ttl:
            return cached[1]
        return None

    async def rules(self, origin: str) -> RobotsRules:
        """Quy tắc của `origin` (ví dụ `https://shop.example`). Ném `RobotsUnavailable` nếu lỗi."""
        hit = self._fresh(origin)
        if hit is not None:
            return hit
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            hit = self._fresh(origin)
            if hit is not None:
                return hit
            status, text = await self._loader(origin)
            rules = self._interpret(origin, status, text)
            self._cache[origin] = (self._clock(), rules)
            return rules

    def _interpret(self, origin: str, status: int, text: str) -> RobotsRules:
        if 200 <= status < 300:
            return parse_robots(text, self._user_agent)
        if status in (401, 403):
            return DISALLOW_ALL  # thận trọng, giống urllib.robotparser
        if 400 <= status < 500 and status != 429:
            return ALLOW_ALL  # 404/410...: không có robots.txt, được phép theo chuẩn
        raise RobotsUnavailable(f"robots.txt returned HTTP {status}", url=f"{origin}/robots.txt")
