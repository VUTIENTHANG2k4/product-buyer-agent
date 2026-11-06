"""T6.7a: LLM trích thông số chạy ngoài giao dịch lưu của trang; cache được commit riêng."""

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sqlmodel import Session, select

from app.agent.prompt_loader import load_prompt
from app.agent.testing import ScriptedChatModel
from app.db.models import LlmExtractionCache, Product
from app.domain.clock import utc_now
from app.domain.dto import ListingItem
from app.domain.enums import Category, SiteKey
from app.normalize.llm_extract import LlmSpecsFiller
from app.normalize.specs import LaptopSpecs
from app.scrapers.pipeline.resolve import resolve_product
from app.scrapers.pipeline.state import PreparedItem
from app.scrapers.pipeline.writer import OfferWriter
from app.scrapers.registry import SCRAPERS

ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'


class ProbeFiller(LlmSpecsFiller):
    """Ghi lại số session đang mở tại thời điểm gọi LLM."""

    def __init__(self, open_sessions: Callable[[], int]) -> None:
        super().__init__(ScriptedChatModel(script=[]), load_prompt("extractor"), model_name="probe")
        self._open_sessions = open_sessions
        self.open_during_calls: list[int] = []

    def _call_llm(
        self, schema: Any, title: str, raw_specs: Mapping[str, str]
    ) -> dict[str, Any] | None:
        self.llm_calls += 1
        self.open_during_calls.append(self._open_sessions())
        return LaptopSpecs(gpu_model="RTX 4050").model_dump(mode="json", exclude_none=True)


class Tracker:
    """Session factory đếm số session đang mở (đóng khi thoát `with`)."""

    def __init__(self, db_session: Session) -> None:
        self._bind = db_session.get_bind()
        self.open = 0

    def __call__(self) -> Session:
        tracker = self

        class Tracked(Session):
            def __enter__(self) -> "Tracked":
                tracker.open += 1
                return self

            def __exit__(self, *exc: object) -> None:
                tracker.open -= 1
                super().__exit__(*exc)

        return Tracked(bind=self._bind, join_transaction_mode="create_savepoint")


def listing(slug: str, price: int | None = 1_000_000) -> ListingItem:
    return ListingItem(
        site=SiteKey.gearvn,
        url=f"https://gearvn.com/products/{slug}",
        title=ACER,
        price=price,
        raw_specs={"Ghi chú": "Card rời RTX 4050 6GB"},
    )


@pytest.fixture
def tracker(db_session: Session) -> Tracker:
    return Tracker(db_session)


def writer(tracker: Tracker, filler: LlmSpecsFiller | None) -> OfferWriter:
    return OfferWriter(tracker, utc_now, resolve_product, filler)


def test_llm_runs_while_no_session_is_open(tracker: Tracker) -> None:
    filler = ProbeFiller(lambda: tracker.open)

    out = writer(tracker, filler).prefill_specs(Category.laptop, [PreparedItem(listing("a"))])

    assert filler.open_during_calls == [0]
    assert out[0].extraction is not None and not out[0].extraction.missing
    assert out[0].extraction.specs["gpu_model"] == "RTX 4050"


def test_cache_survives_even_if_the_item_fails_to_save(
    tracker: Tracker, db_session: Session
) -> None:
    filler = ProbeFiller(lambda: tracker.open)
    unpriced = PreparedItem(listing("a", price=None))

    out = writer(tracker, filler).prefill_specs(Category.laptop, [unpriced])
    config = SCRAPERS[SiteKey.gearvn].config
    # mục không có giá: save_item ném, savepoint hoàn tác
    with pytest.raises(ValueError), db_session.begin_nested():
        writer(tracker, filler).save_item(
            db_session,
            config,
            Category.laptop,
            unpriced.item,
            None,
            utc_now(),
            extraction=out[0].extraction,
        )

    assert len(db_session.exec(select(LlmExtractionCache)).all()) == 1


def test_second_page_with_same_input_hits_the_cache(tracker: Tracker) -> None:
    filler = ProbeFiller(lambda: tracker.open)
    w = writer(tracker, filler)

    w.prefill_specs(Category.laptop, [PreparedItem(listing("a"))])
    w.prefill_specs(Category.laptop, [PreparedItem(listing("b"))])

    assert (filler.llm_calls, filler.cache_hits) == (1, 1)


def test_save_item_uses_the_prefilled_extraction_without_a_filler(
    tracker: Tracker, db_session: Session
) -> None:
    filler = ProbeFiller(lambda: tracker.open)
    w = writer(tracker, filler)
    prepared = w.prefill_specs(Category.laptop, [PreparedItem(listing("a"))])[0]
    config = SCRAPERS[SiteKey.gearvn].config

    offer_id, _ = OfferWriter(tracker, utc_now, resolve_product).save_item(
        db_session,
        config,
        Category.laptop,
        prepared.item,
        None,
        utc_now(),
        extraction=prepared.extraction,
    )

    product = db_session.exec(select(Product)).one()
    assert offer_id > 0
    assert product.specs["gpu_model"] == "RTX 4050"
    assert filler.llm_calls == 1


def test_without_filler_prefill_returns_items_unchanged(tracker: Tracker) -> None:
    items = [PreparedItem(listing("a"))]

    assert writer(tracker, None).prefill_specs(Category.laptop, items) is items


def test_prefill_never_raises_when_the_filler_crashes(tracker: Tracker) -> None:
    class Boom(ProbeFiller):
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("LLM hỏng")

    out = writer(tracker, Boom(lambda: 0)).prefill_specs(
        Category.laptop, [PreparedItem(listing("a"))]
    )

    assert out[0].extraction is None
