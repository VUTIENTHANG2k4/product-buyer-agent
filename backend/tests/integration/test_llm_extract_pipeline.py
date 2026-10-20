"""T5.3: LLM dự phòng nối vào resolve_product, cache lưu trong PostgreSQL."""

from sqlmodel import Session, select

from app.agent.prompts import load_prompt
from app.agent.testing import ScriptedChatModel
from app.db.models import LlmExtractionCache, Product
from app.domain.dto import ListingItem
from app.domain.enums import Category, SiteKey
from app.normalize.llm_extract import LlmSpecsFiller
from app.normalize.specs import LaptopSpecs
from app.scrapers.pipeline import make_resolver, resolve_product

ACER = 'Laptop Acer Aspire Lite 15 AL15-53P-56QH (Core 5-120U/ 8GB/ 512GB/ 15.6" FHD/ Win 11)'


def listing(slug: str = "a") -> ListingItem:
    return ListingItem(
        site=SiteKey.gearvn, url=f"https://gearvn.example/p/{slug}", title=ACER, price=1_000_000
    )


def make_filler(*script: object) -> tuple[LlmSpecsFiller, ScriptedChatModel]:
    model = ScriptedChatModel(script=list(script))
    return LlmSpecsFiller(model, load_prompt("extractor"), model_name="fake-1"), model


def stored_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    assert product is not None
    return product


def test_new_product_gets_missing_field_from_llm_and_full_confidence(db_session: Session) -> None:
    fill, model = make_filler(LaptopSpecs(gpu_model="RTX 4050"))

    resolution = resolve_product(db_session, Category.laptop, listing(), None, spec_filler=fill)

    product = stored_product(db_session, resolution.product_id)
    assert product.specs["gpu_model"] == "RTX 4050"
    assert product.specs["gpu_rank"] == 30
    assert product.specs_confidence == 1.0
    assert len(model.calls) == 1


def test_result_is_cached_in_postgres_and_reused_across_items(db_session: Session) -> None:
    fill, model = make_filler(LaptopSpecs(gpu_model="RTX 4050"))

    resolve_product(db_session, Category.laptop, listing("a"), None, spec_filler=fill)
    resolve_product(db_session, Category.laptop, listing("b"), None, spec_filler=fill)

    rows = db_session.exec(select(LlmExtractionCache)).all()
    assert len(rows) == 1
    assert (rows[0].category, rows[0].model) == (Category.laptop, "fake-1")
    assert rows[0].result["gpu_model"] == "RTX 4050"
    assert (fill.llm_calls, fill.cache_hits, len(model.calls)) == (1, 1, 1)


def test_without_filler_nothing_is_called_and_gpu_stays_missing(db_session: Session) -> None:
    resolution = resolve_product(db_session, Category.laptop, listing(), None)

    product = stored_product(db_session, resolution.product_id)
    assert "gpu_model" not in product.specs
    assert product.specs_confidence < 0.5
    assert db_session.exec(select(LlmExtractionCache)).all() == []


def test_llm_error_does_not_fail_the_item(db_session: Session) -> None:
    fill, _ = make_filler(RuntimeError("LLM hỏng"))

    resolution = resolve_product(db_session, Category.laptop, listing(), None, spec_filler=fill)

    assert "gpu_model" not in stored_product(db_session, resolution.product_id).specs
    assert db_session.exec(select(LlmExtractionCache)).all() == []


def test_make_resolver_passes_the_filler_through(db_session: Session) -> None:
    fill, _ = make_filler(LaptopSpecs(gpu_model="RTX 4060"))

    resolution = make_resolver(fill)(db_session, Category.laptop, listing(), None, {})

    assert stored_product(db_session, resolution.product_id).specs["gpu_rank"] == 40
