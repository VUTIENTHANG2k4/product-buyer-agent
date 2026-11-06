"""QA T6.7a: `OfferWriter.prefill_specs` và `resolve_product(extraction=...)` ở các ca biên.

LLM giả (`ScriptedChatModel`/lớp con của `LlmSpecsFiller`), không gọi mạng. Session dùng chung
connection của `db_session` (savepoint) nên dữ liệu được rollback sau mỗi test.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.agent.prompt_loader import load_prompt
from app.agent.testing import ScriptedChatModel
from app.db.models import LlmExtractionCache, Product
from app.domain.clock import utc_now
from app.domain.dto import ListingItem, ProductDetail
from app.domain.enums import Category, SiteKey
from app.normalize.extract import SpecsExtraction, extract_specs
from app.normalize.llm_extract import LlmSpecsFiller
from app.normalize.specs import LaptopSpecs
from app.scrapers.pipeline.resolve import make_resolver, resolve_product, url_key
from app.scrapers.pipeline.state import PreparedItem
from app.scrapers.pipeline.writer import OfferWriter
from app.scrapers.registry import SCRAPERS
from tests.service_support import add_offer, add_product

CONFIG = SCRAPERS[SiteKey.gearvn].config
ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'
GPU_NOTE = {"Ghi chú": "Card rời RTX 4050 6GB"}


class SpyFiller(LlmSpecsFiller):
    """Ghi lại bảng thông số thô mà mỗi lần gọi nhận; luôn "tìm" ra RTX 4050."""

    def __init__(self) -> None:
        super().__init__(ScriptedChatModel(script=[]), load_prompt("extractor"), model_name="spy")
        self.seen_raw: list[dict[str, Any]] = []
        self.titles: list[str] = []

    def _call_llm(
        self, schema: Any, title: str, raw_specs: Mapping[str, str]
    ) -> dict[str, Any] | None:
        self.llm_calls += 1
        self.seen_raw.append(dict(raw_specs))
        self.titles.append(title)
        return LaptopSpecs(gpu_model="RTX 4050").model_dump(mode="json", exclude_none=True)


def listing(
    url: str, *, price: int | None = 1_000_000, title: str = ACER, raw: bool = True
) -> ListingItem:
    return ListingItem(
        site=SiteKey.gearvn,
        url=url,
        title=title,
        price=price,
        raw_specs=dict(GPU_NOTE) if raw else {},
    )


def gearvn(slug: str) -> str:
    return f"https://gearvn.com/products/{slug}"


@pytest.fixture
def factory(db_session: Session) -> Any:
    bind = db_session.get_bind()

    def make() -> Session:
        return Session(bind=bind, join_transaction_mode="create_savepoint")

    return make


def writer(factory: Any, filler: LlmSpecsFiller | None) -> OfferWriter:
    return OfferWriter(factory, utc_now, resolve_product, filler)


# ---- trang rỗng / toàn mục bị bỏ qua ----------------------------------------------------------
def test_an_empty_page_returns_an_empty_list_and_never_calls_the_llm(factory: Any) -> None:
    filler = SpyFiller()

    out = writer(factory, filler).prefill_specs(CONFIG, Category.laptop, [])

    assert out == []
    assert filler.llm_calls == 0


def test_a_page_where_every_item_is_skipped_keeps_order_and_makes_no_llm_call(
    factory: Any,
) -> None:
    filler = SpyFiller()
    items = [
        PreparedItem(listing(gearvn("a"), price=None)),
        PreparedItem(listing(gearvn("b"), price=0)),
        PreparedItem(listing(gearvn("c"), price=10**13)),
        PreparedItem(listing("https://other.example/p/x")),
        PreparedItem(listing("https://gearvn.com/")),  # trang chủ, không phải sản phẩm
    ]

    out = writer(factory, filler).prefill_specs(CONFIG, Category.laptop, items)

    assert [o.item for o in out] == [i.item for i in items]
    assert all(o.extraction is None for o in out)
    assert filler.llm_calls == 0


# ---- filler lỗi / trả kết quả thiếu -----------------------------------------------------------
def test_one_crashing_item_does_not_stop_the_other_items_of_the_page(factory: Any) -> None:
    class FlakyFiller(SpyFiller):
        def __call__(self, cache: Any, category: Any, title: str, *args: Any) -> Any:
            if "boom" in title:
                raise RuntimeError("LLM hỏng")
            return super().__call__(cache, category, title, *args)

    items = [
        PreparedItem(listing(gearvn("one"), title=ACER)),
        PreparedItem(listing(gearvn("two"), title=ACER + " boom")),
        PreparedItem(listing(gearvn("three"), title=ACER + " ok")),
    ]

    out = writer(factory, FlakyFiller()).prefill_specs(CONFIG, Category.laptop, items)

    assert [o.extraction is not None for o in out] == [True, False, True]


def test_filler_returning_an_extraction_that_still_misses_fields_is_kept_as_is(
    factory: Any,
) -> None:
    class Useless(SpyFiller):
        def __call__(self, cache: Any, category: Any, title: str, raw: Any, extraction: Any) -> Any:
            return extraction  # LLM không điền thêm được gì

    out = writer(factory, Useless()).prefill_specs(
        CONFIG, Category.laptop, [PreparedItem(listing(gearvn("a"), raw=False))]
    )

    assert out[0].extraction is not None
    assert out[0].extraction.missing  # còn thiếu trường bắt buộc
    assert out[0].extraction.confidence < 1.0


def test_filler_that_returns_garbage_never_escapes_prefill(factory: Any) -> None:
    class Garbage(SpyFiller):
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return None  # không phải SpecsExtraction

    out = writer(factory, Garbage()).prefill_specs(
        CONFIG, Category.laptop, [PreparedItem(listing(gearvn("a"), raw=False))]
    )

    # Không được giữ `None` do filler trả về thành "extraction" hợp lệ mà bước lưu sẽ crash
    assert len(out) == 1
    assert out[0].extraction is None or isinstance(out[0].extraction, SpecsExtraction)


def test_session_factory_failing_while_reading_old_offers_returns_the_page_unchanged() -> None:
    def broken() -> Session:
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    items = [PreparedItem(listing(gearvn("a")))]
    filler = SpyFiller()

    out = OfferWriter(broken, utc_now, resolve_product, filler).prefill_specs(
        CONFIG, Category.laptop, items
    )

    assert out is items
    assert filler.llm_calls == 0


# ---- raw_specs lạ / offer đã có ---------------------------------------------------------------
def test_old_raw_specs_with_numbers_and_null_do_not_break_prefill_or_the_save_step(
    db_session: Session, factory: Any
) -> None:
    product = add_product(db_session, category=Category.laptop, specs={})
    url = gearvn("legacy")
    add_offer(
        db_session,
        product,
        site=SiteKey.gearvn,
        url=url,
        raw_specs={"RAM": 16, "Card": None, "Cổng": ["USB", "HDMI"], "Ghi chú": "RTX 4050"},
    )
    filler = SpyFiller()
    w = writer(factory, filler)

    prepared = w.prefill_specs(CONFIG, Category.laptop, [PreparedItem(listing(url, raw=False))])
    offer_id, _ = w.save_item(
        db_session,
        CONFIG,
        Category.laptop,
        prepared[0].item,
        None,
        utc_now(),
        extraction=prepared[0].extraction,
    )

    assert prepared[0].extraction is not None
    assert offer_id > 0


def test_existing_offer_raw_specs_are_merged_into_what_the_llm_sees(
    db_session: Session, factory: Any
) -> None:
    product = add_product(db_session, category=Category.laptop, specs={})
    url = gearvn("with-old-raw")
    add_offer(
        db_session,
        product,
        site=SiteKey.gearvn,
        url=url,
        raw_specs={"Nhãn cũ": "giá trị cũ", "Ghi chú": "cũ"},
    )
    filler = SpyFiller()
    item = ListingItem(
        site=SiteKey.gearvn, url=url, title=ACER, price=1_000_000, raw_specs={"Ghi chú": "mới"}
    )
    detail = ProductDetail(
        site=SiteKey.gearvn, url=url, title=ACER, price=1_000_000, raw_specs={"Chi tiết": "x"}
    )

    writer(factory, filler).prefill_specs(CONFIG, Category.laptop, [PreparedItem(item, detail)])

    assert filler.seen_raw == [{"Nhãn cũ": "giá trị cũ", "Ghi chú": "mới", "Chi tiết": "x"}]


def test_scheme_twin_of_a_stored_offer_still_supplies_its_old_raw_specs(
    db_session: Session, factory: Any
) -> None:
    product = add_product(db_session, category=Category.laptop, specs={})
    add_offer(
        db_session,
        product,
        site=SiteKey.gearvn,
        url="http://gearvn.com/products/twin",
        raw_specs={"Nhãn cũ": "còn giữ"},
    )
    filler = SpyFiller()

    writer(factory, filler).prefill_specs(
        CONFIG,
        Category.laptop,
        [PreparedItem(listing("https://gearvn.com/products/twin", raw=False))],
    )

    assert filler.seen_raw == [{"Nhãn cũ": "còn giữ"}]


# ---- khử trùng URL ----------------------------------------------------------------------------
def test_http_and_https_versions_of_one_url_on_a_page_cost_a_single_llm_call(
    factory: Any,
) -> None:
    filler = SpyFiller()
    items = [
        PreparedItem(listing("https://gearvn.com/products/same")),
        PreparedItem(listing("http://gearvn.com/products/same")),
    ]

    out = writer(factory, filler).prefill_specs(CONFIG, Category.laptop, items)

    assert [o.extraction is not None for o in out] == [True, False]
    assert filler.llm_calls == 1


def test_query_parameter_order_does_not_create_two_urls_but_values_do(factory: Any) -> None:
    filler = SpyFiller()
    items = [
        PreparedItem(listing(gearvn("q") + "?a=1&b=2")),
        PreparedItem(listing(gearvn("q") + "?b=2&a=1")),  # cùng khóa sau clean_url
        PreparedItem(listing(gearvn("q") + "?a=2&b=2")),  # URL khác
        PreparedItem(listing(gearvn("q") + "?utm_source=x&a=1&b=2")),  # theo dõi bị bỏ: trùng
    ]

    out = writer(factory, filler).prefill_specs(CONFIG, Category.laptop, items)

    assert [o.extraction is not None for o in out] == [True, False, True, False]


def test_a_url_already_seen_in_a_resumed_run_is_not_sent_to_the_llm(factory: Any) -> None:
    filler = SpyFiller()
    seen_http = {url_key(listing("http://gearvn.com/products/resumed")) or ""}

    out = writer(factory, filler).prefill_specs(
        CONFIG,
        Category.laptop,
        [PreparedItem(listing("https://gearvn.com/products/resumed"))],
        seen=seen_http,
    )

    assert out[0].extraction is None
    assert filler.llm_calls == 0


def test_the_seen_set_passed_in_is_not_mutated(factory: Any) -> None:
    seen: set[str] = set()

    writer(factory, SpyFiller()).prefill_specs(
        CONFIG, Category.laptop, [PreparedItem(listing(gearvn("a")))], seen=seen
    )

    assert seen == set()


def test_second_page_repeating_a_url_of_the_first_page_does_not_reach_the_llm(
    factory: Any,
) -> None:
    filler = SpyFiller()
    w = writer(factory, filler)
    first = listing(gearvn("again"))
    w.prefill_specs(CONFIG, Category.laptop, [PreparedItem(first)])

    out = w.prefill_specs(
        CONFIG,
        Category.laptop,
        [PreparedItem(listing(gearvn("again"), title=ACER + " v2"))],
        seen={url_key(first) or ""},
    )

    assert out[0].extraction is None
    assert filler.llm_calls == 1


def test_a_nul_in_the_title_never_makes_prefill_raise(factory: Any) -> None:
    filler = SpyFiller()
    items = [
        PreparedItem(listing(gearvn("nul"), title=ACER + "\x00 NUL")),
        PreparedItem(listing(gearvn("fine"))),
    ]

    out = writer(factory, filler).prefill_specs(CONFIG, Category.laptop, items)

    assert len(out) == 2
    assert out[1].extraction is not None


def test_a_nul_in_the_title_cannot_poison_the_llm_cache_for_other_items(
    db_session: Session, factory: Any
) -> None:
    filler = SpyFiller()

    writer(factory, filler).prefill_specs(
        CONFIG, Category.laptop, [PreparedItem(listing(gearvn("nul"), title=ACER + "\x00"))]
    )

    rows = db_session.exec(select(LlmExtractionCache)).all()
    assert all("\x00" not in str(row.result) for row in rows)


# ---- BUG-T67-1 --------------------------------------------------------------------------------
def test_a_duplicate_after_an_unpriced_first_copy_is_skipped_so_it_costs_no_llm_call(
    factory: Any,
) -> None:
    filler = SpyFiller()
    items = [
        PreparedItem(listing(gearvn("dup"), price=None)),
        PreparedItem(listing(gearvn("dup"), price=1_000_000)),
    ]

    out = writer(factory, filler).prefill_specs(CONFIG, Category.laptop, items)

    assert out[1].extraction is None
    assert filler.llm_calls == 0


# ---- resolve_product(extraction=...) ----------------------------------------------------------
def fake_extraction(**specs: Any) -> SpecsExtraction:
    return SpecsExtraction(specs=specs, missing=(), confidence=1.0)


def test_resolve_product_with_extraction_never_runs_the_filler_or_the_rules(
    db_session: Session,
) -> None:
    filler = SpyFiller()
    item = listing(gearvn("pre"), raw=False)

    resolution = resolve_product(
        db_session,
        Category.laptop,
        item,
        None,
        None,
        spec_filler=filler,
        extraction=fake_extraction(ram_gb=64, cpu_model="Ghost CPU"),
    )

    product = db_session.get(Product, resolution.product_id)
    assert product is not None
    assert product.specs == {"ram_gb": 64, "cpu_model": "Ghost CPU"}
    assert product.specs_confidence == 1.0
    assert filler.llm_calls == 0


def test_resolve_product_without_extraction_still_uses_the_filler_when_rules_miss_fields(
    db_session: Session,
) -> None:
    filler = SpyFiller()

    resolution = resolve_product(
        db_session,
        Category.laptop,
        listing(gearvn("rules")),
        None,
        None,
        spec_filler=filler,
    )

    product = db_session.get(Product, resolution.product_id)
    assert product is not None
    assert filler.llm_calls == 1
    assert product.specs["gpu_model"] == "RTX 4050"


def test_make_resolver_forwards_the_prefilled_extraction(db_session: Session) -> None:
    filler = SpyFiller()
    resolver = make_resolver(filler)

    resolution = resolver(
        db_session,
        Category.laptop,
        listing(gearvn("forward"), raw=False),
        None,
        {},
        extraction=fake_extraction(ram_gb=32),
    )

    product = db_session.get(Product, resolution.product_id)
    assert product is not None and product.specs == {"ram_gb": 32}
    assert filler.llm_calls == 0


def test_prefilled_extraction_equals_the_inline_path_for_the_same_input(
    db_session: Session, factory: Any
) -> None:
    """Hai đường (làm sẵn rồi lưu / lưu thẳng với filler) cho cùng thông số sản phẩm."""
    filler = SpyFiller()
    w = writer(factory, filler)
    a = listing(gearvn("path-a"), title=ACER + " A")
    b = listing(gearvn("path-b"), title=ACER + " B")

    prepared = w.prefill_specs(CONFIG, Category.laptop, [PreparedItem(a)])[0]
    via_prefill = resolve_product(
        db_session, Category.laptop, a, None, a.raw_specs, extraction=prepared.extraction
    )
    inline = resolve_product(db_session, Category.laptop, b, None, b.raw_specs, spec_filler=filler)

    p1 = db_session.get(Product, via_prefill.product_id)
    p2 = db_session.get(Product, inline.product_id)
    assert p1 is not None and p2 is not None
    assert p1.specs == p2.specs
    assert p1.specs_confidence == p2.specs_confidence
    assert extract_specs(Category.laptop, a.title, a.raw_specs).specs.items() <= p1.specs.items()
