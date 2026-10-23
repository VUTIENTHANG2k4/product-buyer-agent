"""T10.3: tool `live_search_other` gọi `live_search_service` (service giả, không cần CSDL)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.tools import BaseTool

from app.agent.executor import summarize_result
from app.agent.tools import MAX_RESULT_CHARS, ToolContext, build_tools
from app.agent.tools.live_search_other import UNAVAILABLE_REASON
from app.domain.enums import SiteKey
from app.domain.errors import ValidationFailed
from app.domain.live_search import LiveSearchItem, LiveSearchResult, SkippedSite
from tests.agent.conftest import call, size
from tests.service_support import make_settings

SCRAPED = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def item(site: SiteKey, n: int, price: int | None = 500_000, title: str = "") -> LiveSearchItem:
    return LiveSearchItem(
        site=site,
        title=title or f"Loa Bluetooth Mock {n}",
        price=price,
        url=f"https://shop.example/{site.value}/loa-{n}",
        scraped_at=SCRAPED,
    )


class StubLiveSearch:
    """Thay `LiveSearchService`: trả kết quả định sẵn (hoặc ném lỗi) và ghi lại tham số."""

    def __init__(self, result: LiveSearchResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def search(self, query: str, **kwargs: Any) -> LiveSearchResult:
        self.calls.append({"query": query, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def tools_with(live: StubLiveSearch | None) -> dict[str, BaseTool]:
    def no_session() -> Any:  # pragma: no cover - tool tầng 2 không dùng session của tool
        raise AssertionError("live_search_other must not open a DB session itself")

    ctx = ToolContext(
        session_factory=no_session,
        settings=make_settings(),
        live_search=live,  # type: ignore[arg-type]
    )
    return {tool.name: tool for tool in build_tools(ctx)}


async def test_without_a_service_the_tool_says_it_is_unavailable() -> None:
    result = await call(tools_with(None), "live_search_other", query="loa bluetooth")

    assert result["ok"] is True and result["items"] == []
    assert result["reason"] == UNAVAILABLE_REASON and result["label"] == "unnormalized"
    assert result["sites_searched"] == [] and result["sites_skipped"] == []


async def test_tool_passes_arguments_and_returns_the_documented_shape() -> None:
    found = LiveSearchResult(
        items=[item(SiteKey.gearvn, 1, 790_000), item(SiteKey.fptshop, 2, None)],
        sites_searched=[SiteKey.gearvn, SiteKey.fptshop],
        sites_skipped=[SkippedSite(site=SiteKey.anphat, reason="trang chặn truy cập")],
        from_cache=True,
    )
    live = StubLiveSearch(found)

    result = await call(
        tools_with(live),
        "live_search_other",
        query="loa bluetooth",
        price_min=100_000,
        price_max=1_000_000,
        limit_per_site=3,
    )

    assert live.calls == [
        {
            "query": "loa bluetooth",
            "price_min": 100_000,
            "price_max": 1_000_000,
            "limit_per_site": 3,
        }
    ]
    assert result["ok"] is True and result["label"] == "unnormalized"
    assert result["from_cache"] is True
    assert result["sites_searched"] == ["gearvn", "fptshop"]
    assert result["sites_skipped"] == [{"site": "anphat", "reason": "trang chặn truy cập"}]
    assert result["items"] == [
        {
            "site": "gearvn",
            "title": "Loa Bluetooth Mock 1",
            "price": 790_000,
            "url": "https://shop.example/gearvn/loa-1",
            "scraped_at": SCRAPED.isoformat(),
        },
        {
            "site": "fptshop",
            "title": "Loa Bluetooth Mock 2",
            "price": None,
            "url": "https://shop.example/fptshop/loa-2",
            "scraped_at": SCRAPED.isoformat(),
        },
    ]
    assert "reason" not in result


async def test_default_limit_per_site_is_five() -> None:
    live = StubLiveSearch(
        LiveSearchResult(items=[], sites_searched=[], sites_skipped=[], from_cache=False)
    )

    result = await call(tools_with(live), "live_search_other", query="ssd 1tb")

    assert live.calls[0]["limit_per_site"] == 5
    assert result["items"] == [] and result["ok"] is True


async def test_long_titles_from_the_web_are_clipped() -> None:
    long_title = "Loa " + "rất dài " * 40
    live = StubLiveSearch(
        LiveSearchResult(
            items=[item(SiteKey.gearvn, 1, title=long_title)],
            sites_searched=[SiteKey.gearvn],
            sites_skipped=[],
            from_cache=False,
        )
    )

    result = await call(tools_with(live), "live_search_other", query="loa")

    title = result["items"][0]["title"]
    assert len(title) <= 120 and title.endswith("…")


async def test_result_is_limited_to_four_thousand_characters() -> None:
    many = [item(SiteKey.gearvn, n, title="Loa " + "x" * 110) for n in range(1, 21)]
    live = StubLiveSearch(
        LiveSearchResult(
            items=many, sites_searched=[SiteKey.gearvn], sites_skipped=[], from_cache=False
        )
    )

    result = await call(tools_with(live), "live_search_other", query="loa", limit_per_site=10)

    assert size(result) <= MAX_RESULT_CHARS
    assert result["truncated"] is True and 0 < len(result["items"]) < 20


async def test_a_domain_error_becomes_a_tool_error_the_model_can_fix() -> None:
    live = StubLiveSearch(error=ValidationFailed("price_min không được lớn hơn price_max."))

    result = await call(
        tools_with(live), "live_search_other", query="loa", price_min=5, price_max=4
    )

    assert result["ok"] is False and result["error"] == "VALIDATION_ERROR"
    assert "price_min" in result["message"]


async def test_an_unexpected_error_is_not_swallowed() -> None:
    live = StubLiveSearch(error=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await call(tools_with(live), "live_search_other", query="loa")


@pytest.mark.parametrize(
    "args", [{"query": ""}, {"query": "x" * 201}, {"query": "loa", "limit_per_site": 11}]
)
async def test_arguments_are_validated_before_the_service_is_called(args: dict[str, Any]) -> None:
    live = StubLiveSearch(
        LiveSearchResult(items=[], sites_searched=[], sites_skipped=[], from_cache=False)
    )

    result = await call(tools_with(live), "live_search_other", **args)

    assert result["error"] == "VALIDATION_ERROR" and live.calls == []


@pytest.mark.parametrize(
    ("result", "summary"),
    [
        (
            {"ok": True, "items": [{}, {}, {}], "sites_searched": ["gearvn", "fptshop"]},
            "Tìm trực tiếp: 3 kết quả từ 2 trang",
        ),
        (
            {
                "ok": True,
                "items": [{}],
                "sites_searched": ["gearvn"],
                "sites_skipped": [{"site": "fptshop", "reason": "x"}],
            },
            "Tìm trực tiếp: 1 kết quả từ 1 trang, bỏ qua 1 trang",
        ),
        ({"ok": True, "items": [], "sites_searched": []}, "Tìm trực tiếp: 0 kết quả từ 0 trang"),
        ({"ok": True, "reason": UNAVAILABLE_REASON}, "Tìm trực tiếp chưa khả dụng"),
        ({"ok": False, "message": "Từ khóa trống"}, "Từ khóa trống"),
    ],
)
def test_tool_end_summary_counts_results_and_skipped_sites(
    result: dict[str, Any], summary: str
) -> None:
    assert summarize_result("live_search_other", result) == summary
