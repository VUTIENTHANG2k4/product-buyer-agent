"""Fetcher và `ScrapeService` dùng chung trong một tiến trình API (dựng lười, đóng khi tắt app).

Một `Fetcher` duy nhất giữ cookie phiên của mock-shop giữa lúc tạo lượt và lúc nhập đáp án captcha
(docs/06 §4), và giữ cache robots.txt cho trang quản trị.
"""

from app.config import Settings
from app.normalize.llm_extract import LlmSpecsFiller
from app.scrapers.http.factory import build_fetcher
from app.scrapers.http.fetcher import Fetcher
from app.services.alert_evaluation import AlertEvaluator
from app.services.database import session_factory
from app.services.notifier import build_notifiers
from app.services.scrape_service import ScrapeService


class ScrapeRuntime:
    def __init__(self, service: ScrapeService, fetcher: Fetcher) -> None:
        self.service = service
        self.fetcher = fetcher

    @classmethod
    def build(
        cls, settings: Settings, spec_filler: LlmSpecsFiller | None = None
    ) -> "ScrapeRuntime":
        """Dựng Fetcher thật và `ScrapeService` từ cấu hình; `spec_filler`: LLM dự phòng."""
        fetcher = build_fetcher(settings)
        factory = session_factory(settings.database_url.get_secret_value())
        service = ScrapeService(
            factory,
            fetcher,
            settings,
            on_price_changes=AlertEvaluator(factory, build_notifiers(settings), settings),
            spec_filler=spec_filler,
        )
        return cls(service, fetcher)

    async def aclose(self) -> None:
        await self.fetcher.aclose()
