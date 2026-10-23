"""Fetcher và `ScrapeService` dùng chung trong một tiến trình API (dựng lười, đóng khi tắt app).

Một `Fetcher` duy nhất giữ cookie phiên của mock-shop giữa lúc tạo lượt và lúc nhập đáp án captcha
(docs/06 §4), và giữ cache robots.txt cho trang quản trị. `LiveSearchService` (tầng 2) dùng chung
Fetcher này nên tìm trực tiếp và thu thập cùng tôn trọng một bộ giới hạn ≥ 5 s/domain.
"""

from app.config import Settings
from app.normalize.llm_extract import LlmSpecsFiller
from app.scrapers.http.factory import build_fetcher
from app.scrapers.http.fetcher import Fetcher
from app.services.alert_evaluation import AlertEvaluator
from app.services.database import session_factory
from app.services.live_search_service import LiveSearchService
from app.services.notifier import build_notifiers
from app.services.scrape_service import ScrapeService


class ScrapeRuntime:
    def __init__(
        self,
        service: ScrapeService,
        fetcher: Fetcher,
        alert_evaluator: AlertEvaluator | None = None,
        live_search: LiveSearchService | None = None,
    ) -> None:
        self.service = service
        self.fetcher = fetcher
        self.alert_evaluator = alert_evaluator  # worker gọi `evaluate(None)` sau mỗi job
        self.live_search = live_search  # tầng 2; None khi dựng tay trong test

    @classmethod
    def build(
        cls, settings: Settings, spec_filler: LlmSpecsFiller | None = None
    ) -> "ScrapeRuntime":
        """Dựng Fetcher thật và `ScrapeService` từ cấu hình; `spec_filler`: LLM dự phòng."""
        fetcher = build_fetcher(settings)
        factory = session_factory(settings.database_url.get_secret_value())
        evaluator = AlertEvaluator(factory, build_notifiers(settings), settings)
        service = ScrapeService(
            factory, fetcher, settings, on_price_changes=evaluator, spec_filler=spec_filler
        )
        live_search = LiveSearchService(factory, settings, fetcher)
        return cls(service, fetcher, evaluator, live_search)

    async def aclose(self) -> None:
        await self.fetcher.aclose()
