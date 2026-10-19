"""QA M2: robots.txt lạ, rất lớn hoặc thù địch (app/scrapers/http/robots.py)."""

import asyncio
import time

import pytest

from app.scrapers.http.robots import MAX_ROBOTS_CHARS, RobotsCache, parse_robots

UA = "ProductBuyerAgent/0.1 (+test)"
SHOP = "https://shop.example"


def allowed(text: str, path: str) -> bool:
    return parse_robots(text, UA).allowed(f"{SHOP}{path}")


def test_a_pattern_with_many_wildcards_does_not_stall_the_event_loop() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /" + "*a" * 4 + "b\n", UA)
    started = time.perf_counter()
    assert rules.allowed(f"{SHOP}/" + "a" * 200) is True  # không khớp vì thiếu 'b'
    assert time.perf_counter() - started < 0.1


def test_realistic_wildcard_rules_stay_fast_on_long_urls() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /*?*price=*&*sort=*\nDisallow: /*.pdf$\n", UA)
    url = f"{SHOP}/c/laptop?" + "&".join(f"k{i}=v{i}" for i in range(150))
    started = time.perf_counter()
    assert rules.allowed(url) is True
    assert rules.allowed(url + "&price=1&x=1&sort=2") is False
    assert time.perf_counter() - started < 0.5


def test_a_line_without_a_colon_is_ignored_and_does_not_hide_the_next_rules() -> None:
    text = "User-agent: *\nDisallow /ignored\nthis is garbage\nDisallow: /b\n"
    assert allowed(text, "/b") is False
    assert allowed(text, "/c") is True


def test_rules_after_the_500_kib_limit_are_ignored_and_those_before_it_are_kept() -> None:
    padding = "# " + "x" * 1000 + "\n"
    text = "User-agent: *\nDisallow: /early\n" + padding * 520 + "Disallow: /late\n"
    assert len(text) > MAX_ROBOTS_CHARS
    started = time.perf_counter()
    rules = parse_robots(text, UA)
    assert rules.allowed(f"{SHOP}/early") is False
    assert rules.allowed(f"{SHOP}/late") is True  # RFC 9309: phần vượt 500 KiB bị bỏ
    assert time.perf_counter() - started < 2.0


def test_a_single_huge_line_does_not_break_parsing() -> None:
    text = "User-agent: *\nDisallow: /x\n" + "a" * 2_000_000 + "\nDisallow: /y\n"
    assert allowed(text, "/x") is False


def test_several_wildcard_groups_are_merged_not_overwritten() -> None:
    text = "User-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b\n"
    assert (allowed(text, "/a"), allowed(text, "/b"), allowed(text, "/c")) == (False, False, True)


def test_the_longest_rule_wins_and_allow_wins_a_tie_regardless_of_order() -> None:
    longer_allow = "User-agent: *\nAllow: /p/public\nDisallow: /p\n"
    assert allowed(longer_allow, "/p/public/x") is True
    assert allowed(longer_allow, "/p/private") is False
    longer_disallow = "User-agent: *\nAllow: /p\nDisallow: /p/secret\n"
    assert allowed(longer_disallow, "/p/secret/1") is False
    assert allowed(longer_disallow, "/p/open") is True
    tie = "User-agent: *\nDisallow: /same\nAllow: /same\n"
    assert allowed(tie, "/same") is True
    assert allowed("User-agent: *\nAllow: /same\nDisallow: /same\n", "/same") is True


@pytest.mark.parametrize(
    ("rule", "blocked", "open_"),
    [
        ("*", ["/", "/a", "/a?x=1"], []),
        ("/*", ["/", "/a"], []),
        ("$", [], ["/", "/a"]),  # chỉ khớp đường dẫn rỗng, mà URL luôn có ít nhất '/'
        ("/*.pdf$", ["/a.pdf", "/x/y.pdf"], ["/a.pdf?download=1", "/a.pdfx"]),
        ("/a$", ["/a"], ["/a/", "/ab"]),
        ("/search?q=%E1%BA%A1", ["/search?q=ạ", "/search?q=%e1%ba%a1"], ["/search?q=a"]),
    ],
)
def test_degenerate_and_encoded_patterns(rule: str, blocked: list[str], open_: list[str]) -> None:
    text = f"User-agent: *\nDisallow: {rule}\n"
    assert [allowed(text, path) for path in blocked] == [False] * len(blocked)
    assert [allowed(text, path) for path in open_] == [True] * len(open_)


def test_a_group_for_our_product_token_replaces_the_wildcard_group() -> None:
    text = (
        "User-agent: *\nDisallow: /\n\nUser-agent: PRODUCTBUYERAGENT\nAllow: /\nDisallow: /admin\n"
    )
    assert allowed(text, "/c/laptop") is True
    assert allowed(text, "/admin/x") is False


@pytest.mark.parametrize("value", ["nan", "inf", "-5", "1e400", "abc", "1,5", "10 20"])
def test_an_unusable_crawl_delay_is_ignored(value: str) -> None:
    assert parse_robots(f"User-agent: *\nCrawl-delay: {value}\n", UA).crawl_delay is None


def test_crawl_delay_is_taken_from_the_selected_group_only() -> None:
    text = "User-agent: *\nCrawl-delay: 30\n\nUser-agent: productbuyeragent\nCrawl-delay: 7\n"
    assert parse_robots(text, UA).crawl_delay == 7.0


async def test_concurrent_requests_for_one_origin_load_robots_txt_once() -> None:
    calls: list[str] = []

    async def loader(origin: str) -> tuple[int, str]:
        calls.append(origin)
        await asyncio.sleep(0)
        return 200, "User-agent: *\nDisallow: /x\n"

    cache = RobotsCache(loader, UA)
    results = await asyncio.gather(*(cache.rules(SHOP) for _ in range(8)))

    assert calls == [SHOP]
    assert all(rules is results[0] for rules in results)


async def test_origins_that_differ_by_port_or_scheme_have_separate_rules() -> None:
    seen: list[str] = []

    async def loader(origin: str) -> tuple[int, str]:
        seen.append(origin)
        return (403, "") if origin.endswith(":8443") else (200, "")

    cache = RobotsCache(loader, UA)
    assert (await cache.rules(SHOP)).allowed(f"{SHOP}/x") is True
    assert (await cache.rules(f"{SHOP}:8443")).allowed(f"{SHOP}:8443/x") is False
    assert (await cache.rules("http://shop.example")).allowed("http://shop.example/x") is True
    assert seen == [SHOP, f"{SHOP}:8443", "http://shop.example"]
