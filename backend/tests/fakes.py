"""Đối tượng giả dùng chung cho test (không gọi mạng)."""

from app.scrapers.http.types import FetchResponse


class FakeFetcher:
    """Trả phản hồi định sẵn theo URL và ghi lại các URL đã yêu cầu."""

    def __init__(self, pages: dict[str, FetchResponse]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def get(self, url: str) -> FetchResponse:
        self.requested.append(url)
        return self.pages[url]
