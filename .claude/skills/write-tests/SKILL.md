---
name: write-tests
description: Hướng dẫn viết test cho dự án (pytest, respx, mock-shop qua ASGI, ScriptedChatModel, golden YAML, Vitest + MSW, Playwright) đúng chiến lược kiểm thử. Dùng khi viết test cho bất kỳ task nào hoặc tái hiện bug.
---

# Viết test cho dự án

Tài liệu gốc: `docs/09-testing-strategy.md`; quy tắc `.claude/rules/testing.md`.

## Chọn lớp test
| Đang test | Lớp | Thư mục |
| --- | --- | --- |
| Hàm thuần (parser, normalize, gpu_rank, matcher) | Unit (+ golden) | `backend/tests/unit/` |
| Repository, service, API endpoint, pipeline + mock-shop | Integration | `backend/tests/integration/` |
| Tool, planner, executor, guardrail, SSE | Agent | `backend/tests/agent/` |
| Component, hook React | Unit FE | `frontend/src/**/*.test.tsx` |
| Luồng người dùng xuyên suốt | E2E | `frontend/e2e/` |

## Mẫu backend
```python
# Parser trên fixture
def test_parse_listing_laptop_page1(load_fixture, make_scraper):
    html = load_fixture("gearvn/listing_laptop_p1.html")
    scraper = make_scraper(SiteKey.GEARVN)      # fixture tạo scraper với Fetcher giả
    page = scraper.parse_listing(html, Category.LAPTOP, "https://gearvn.com/…")
    assert len(page.items) == 24          # số thật đếm khi khảo sát
    first = page.items[0]
    assert first.title and first.url.host == "gearvn.com"
    assert first.price is None or first.price > 0
    assert page.has_next is True

# HTTP giả
@respx.mock
async def test_fetcher_skips_disallowed_url(fetcher):
    respx.get("https://example.vn/robots.txt").respond(text="User-agent: *\nDisallow: /tim-kiem")
    route = respx.get("https://example.vn/tim-kiem").respond(text="x")
    with pytest.raises(RobotsDisallowed):
        await fetcher.get("https://example.vn/tim-kiem")
    assert not route.called

# Agent với LLM giả
async def test_agent_filters_by_gpu(seeded_db, scripted_model):
    scripted_model.script([
        tool_call("search_catalog", {"category": "laptop", "price_max": 30_000_000,
                                     "spec_filters": [{"field": "gpu_rank", "op": "gte", "value": 40}]}),
        final_answer(product_ids=[...]),
    ])
    events = [e async for e in run_agent("laptop dưới 30 triệu RTX 4060", model=scripted_model)]
    assert [e.event for e in events][:2] == ["plan", "tool_start"]
    assert events[-1].event == "final"
```
(Tên hàm/fixture minh họa; dùng tên thật đã có trong `conftest.py`.)

## Mẫu frontend
```tsx
it("sắp xếp theo giá tăng dần khi bấm tiêu đề cột", async () => {
  render(<ResultsTable rows={mockRows} />);
  await userEvent.click(screen.getByRole("button", { name: /giá thấp nhất/i }));
  const prices = screen.getAllByTestId("min-price").map((n) => n.textContent);
  expect(prices).toEqual(["24.990.000 ₫", "27.490.000 ₫", "29.990.000 ₫"]);
});
```

## Tái hiện bug
1. Viết test thất bại mô tả đúng hành vi mong đợi (tên test nêu rõ bug).
2. Xác nhận test đỏ vì đúng lý do.
3. Sửa code → test xanh → chạy cả bộ.

## Không được
- Gọi mạng thật ngoài `@pytest.mark.live`; `time.sleep` thật; phụ thuộc thứ tự test.
- Khẳng định yếu (`assert result`) khi có thể khẳng định giá trị cụ thể.
- Xóa/skip test hoặc sửa kỳ vọng golden/eval chỉ để cho xanh.
