"""Bộ phân tích robots.txt và bộ nhớ đệm 24 giờ (app/scrapers/http/robots.py)."""

import pytest

from app.scrapers.http.errors import RobotsUnavailable
from app.scrapers.http.robots import ROBOTS_TTL_SECONDS, RobotsCache, parse_robots

UA = "ProductBuyerAgent/0.1 (do-an-sinh-vien; lien-he: x@example.com)"
BASE = "https://shop.example"


def allowed(robots: str, path: str) -> bool:
    return parse_robots(robots, UA).allowed(f"{BASE}{path}")


def test_no_rules_allows_everything() -> None:
    assert allowed("", "/anything?x=1")
    assert allowed("User-agent: *\nDisallow:\n", "/anything")


def test_prefix_rule_blocks_path_and_children_only() -> None:
    robots = "User-agent: *\nDisallow: /admin"
    assert not allowed(robots, "/admin")
    assert not allowed(robots, "/admin/users")
    assert not allowed(robots, "/administrator")  # tiền tố thuần, giống chuẩn
    assert allowed(robots, "/c/laptop")


def test_wildcard_matches_query_parameters_that_stdlib_robotparser_misses() -> None:
    robots = "User-agent: *\nDisallow: /*?filter=\nDisallow: /*specMap="
    assert not allowed(robots, "/laptop?filter=gaming")
    assert not allowed(robots, "/laptop?page=2&specMap=ram")
    assert allowed(robots, "/laptop?page=2")


def test_end_anchor_matches_only_the_exact_end() -> None:
    robots = "User-agent: *\nDisallow: /*.pdf$"
    assert not allowed(robots, "/files/a.pdf")
    assert allowed(robots, "/files/a.pdf?download=1")
    assert allowed(robots, "/files/a.pdfx")


def test_longest_matching_rule_wins_and_allow_wins_a_tie() -> None:
    robots = "User-agent: *\nDisallow: /shop\nAllow: /shop/public"
    assert allowed(robots, "/shop/public/item")
    assert not allowed(robots, "/shop/private")
    tie = "User-agent: *\nDisallow: /same\nAllow: /same"
    assert allowed(tie, "/same")


def test_specific_group_for_our_agent_overrides_the_star_group() -> None:
    robots = "User-agent: *\nDisallow: /\n\nUser-agent: ProductBuyerAgent\nDisallow: /private\n"
    assert allowed(robots, "/c/laptop")
    assert not allowed(robots, "/private/x")


def test_groups_for_other_agents_do_not_apply() -> None:
    robots = "User-agent: ClaudeBot\nDisallow: /\n\nUser-agent: *\nDisallow: /admin"
    assert allowed(robots, "/c/laptop")


def test_consecutive_user_agent_lines_share_one_group() -> None:
    robots = "User-agent: GoogleBot\nUser-agent: productbuyeragent\nDisallow: /x"
    assert not allowed(robots, "/x")


def test_comments_blank_lines_and_unknown_fields_are_ignored() -> None:
    robots = (
        "# hello\nUser-agent: *  # all\nSitemap: https://shop.example/s.xml\nDisallow: /a # c\n"
    )
    assert not allowed(robots, "/a")
    assert allowed(robots, "/b")


def test_field_names_are_case_insensitive_but_paths_are_not() -> None:
    robots = "USER-AGENT: *\nDISALLOW: /Secret"
    assert not allowed(robots, "/Secret")
    assert allowed(robots, "/secret")


@pytest.mark.parametrize(
    ("value", "expected"), [("12", 12.0), ("2.5", 2.5), ("abc", None), ("-1", None), ("inf", None)]
)
def test_crawl_delay_is_read_from_the_selected_group(value: str, expected: float | None) -> None:
    rules = parse_robots(f"User-agent: *\nCrawl-delay: {value}\nDisallow: /x", UA)
    assert rules.crawl_delay == expected


def test_disallow_all_flag_blocks_every_url() -> None:
    from app.scrapers.http.robots import DISALLOW_ALL

    assert not DISALLOW_ALL.allowed(f"{BASE}/")


def test_root_url_without_path_is_matched_as_slash() -> None:
    assert not allowed("User-agent: *\nDisallow: /$", "")


# --- Ca biên từ review M2 ---------------------------------------------------------------------


def test_utf8_bom_at_the_start_does_not_hide_the_first_directive() -> None:
    robots = "﻿User-agent: *\nDisallow: /\n"
    assert not allowed(robots, "/c/laptop")


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("/%7Euser", "/~user/x"),  # pattern mã hóa, URL không
        ("/~user", "/%7Euser/x"),  # ngược lại
        ("/%7euser", "/%7Euser/x"),  # khác hoa/thường của hex
        ("/Đồ", "/%C4%90%E1%BB%93"),  # ký tự Unicode thô so với dạng %XX
        ("/%C4%90%E1%BB%93", "/Đồ"),
    ],
)
def test_percent_encoding_is_normalised_before_matching(pattern: str, path: str) -> None:
    assert not allowed(f"User-agent: *\nDisallow: {pattern}", path)


def test_encoded_reserved_characters_are_not_decoded() -> None:
    robots = "User-agent: *\nDisallow: /a%2Fb"
    assert not allowed(robots, "/a%2fb")
    assert allowed(robots, "/a/b")  # %2F là ký tự đặt riêng, không đồng nghĩa với "/"


@pytest.mark.parametrize("agent", ["o", "a", "bot", "example", "lien-he", "do-an-sinh-vien"])
def test_agent_names_that_are_only_substrings_of_our_user_agent_do_not_match(agent: str) -> None:
    robots = f"User-agent: {agent}\nDisallow: /\n\nUser-agent: *\nDisallow: /admin"
    assert allowed(robots, "/c/laptop")
    assert not allowed(robots, "/admin")  # nhóm `*` vẫn áp dụng cho ta


def test_agent_line_with_a_version_still_matches_our_product_token() -> None:
    assert not allowed("User-agent: ProductBuyerAgent/1.0\nDisallow: /x", "/x")


def test_user_agent_matching_is_case_insensitive() -> None:
    assert not allowed("USER-AGENT: PRODUCTBUYERAGENT\nDisallow: /x", "/x")


def test_huge_crawl_delay_is_capped() -> None:
    from app.scrapers.http.robots import MAX_CRAWL_DELAY_SECONDS

    rules = parse_robots("User-agent: *\nCrawl-delay: 1000000000", UA)
    assert rules.crawl_delay == MAX_CRAWL_DELAY_SECONDS


def test_rules_that_do_not_start_with_a_slash_or_star_never_match_normal_paths() -> None:
    assert allowed("User-agent: *\nDisallow: admin", "/admin")


def test_crlf_line_endings_are_handled() -> None:
    assert not allowed("User-agent: *\r\nDisallow: /x\r\n", "/x")


class Loader:
    def __init__(self, *results: tuple[int, str] | Exception) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def __call__(self, origin: str) -> tuple[int, str]:
        self.calls.append(origin)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_cache_loads_once_per_origin_within_24_hours() -> None:
    clock, loader = Clock(), Loader((200, "User-agent: *\nDisallow: /a"), (404, ""))
    cache = RobotsCache(loader, UA, clock=clock)

    first = await cache.rules(BASE)
    clock.now = ROBOTS_TTL_SECONDS - 1
    again = await cache.rules(BASE)
    assert again is first
    assert loader.calls == [BASE]

    clock.now = ROBOTS_TTL_SECONDS
    refreshed = await cache.rules(BASE)
    assert loader.calls == [BASE, BASE]
    assert refreshed.allowed(f"{BASE}/a")  # lần tải thứ hai là 404 → cho phép


@pytest.mark.parametrize(
    ("status", "can_fetch"), [(404, True), (410, True), (403, False), (401, False)]
)
async def test_client_errors_follow_the_standard(status: int, can_fetch: bool) -> None:
    cache = RobotsCache(Loader((status, "")), UA)
    assert (await cache.rules(BASE)).allowed(f"{BASE}/c/laptop") is can_fetch


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_server_errors_are_unavailable_and_not_cached(status: int) -> None:
    loader = Loader((status, ""), (200, ""))
    cache = RobotsCache(loader, UA)
    with pytest.raises(RobotsUnavailable):
        await cache.rules(BASE)
    await cache.rules(BASE)  # lần sau thử lại
    assert len(loader.calls) == 2


async def test_loader_errors_are_not_cached() -> None:
    loader = Loader(RobotsUnavailable("down", url=f"{BASE}/robots.txt"), (200, ""))
    cache = RobotsCache(loader, UA)
    with pytest.raises(RobotsUnavailable):
        await cache.rules(BASE)
    assert (await cache.rules(BASE)).allowed(f"{BASE}/x")


async def test_origins_are_cached_separately() -> None:
    loader = Loader((200, ""), (200, ""))
    cache = RobotsCache(loader, UA)
    await cache.rules("https://a.example")
    await cache.rules("https://b.example")
    assert loader.calls == ["https://a.example", "https://b.example"]
