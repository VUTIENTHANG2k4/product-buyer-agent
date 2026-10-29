"""Ghép lại offer đã có theo luật chuẩn hóa hiện tại (`make rematch`, T5.4; docs/04 §7).

Pipeline không bao giờ xét lại offer đã có, nên khi `detect_brand` hay luật ghép đổi thì lỗi ghép cũ
nằm yên trong CSDL. Lượt ghép lại đọc lại `title` + `raw_specs` của từng offer trong nhóm (theo id
tăng dần), tính lại hãng, mã model, tên chuẩn, thông số rồi ghép như offer mới vào tập "sản phẩm
đích" dựng dần. Offer đầu của một mẫu giữ sản phẩm hiện tại (giữ id để danh sách mua và cảnh báo
không bị xáo trộn) nếu sản phẩm đó chưa thuộc mẫu khác; không thì tạo sản phẩm mới.

Specs của mỗi sản phẩm đích được dựng lại từ mọi offer của nó: nhãn bảng thông số > specs cũ của
sản phẩm giữ lại (seed, LLM dự phòng) > tiêu đề, cùng nguồn thì offer cũ hơn thắng, giá trị đủ thay
giá trị yếu. Khi ghép, mã model đang có của laptop thắng mã đọc từ tên (có thể đến từ MPN) và specs
cũ bù trường mà tiêu đề/bảng thông số không có. Sản phẩm không còn offer
bị xóa, trừ khi còn nằm trong danh sách mua hoặc có cảnh báo giá (giữ lại và báo).

Không gọi mạng, không gọi LLM. Offer không lưu `brand_hint`/`model_code_hint` của trang chi tiết nên
kết quả có thể khác lần ghép đầu (rõ nhất với mock-shop, nơi MPN là mã model laptop).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.db.models import Offer, Product
from app.db.repositories import OfferRepository, ProductRepository
from app.domain.enums import Category, MatchMethod, SiteKey
from app.normalize.brand import detect_brand
from app.normalize.extract import SpecsExtraction, extract_specs, merge_specs, specs_confidence
from app.normalize.matcher import Candidate, decide_match
from app.normalize.model_code import extract_model_code
from app.normalize.names import canonical_name

logger = logging.getLogger(__name__)

REMATCH_CATEGORIES = (Category.laptop, Category.mouse, Category.keyboard, Category.headset)


@dataclass(frozen=True)
class OfferMove:
    offer_id: int
    title: str
    from_product_id: int
    to_product_id: int | None  # None: sản phẩm mới (chạy thử chưa có id)
    method: MatchMethod


@dataclass
class RematchReport:
    """Kết quả một lượt (chạy thử: điều sẽ xảy ra; `--apply`: điều đã ghi)."""

    applied: bool
    offers_checked: int = 0
    moves: list[OfferMove] = field(default_factory=list)
    products_created: int = 0
    products_renamed: list[int] = field(default_factory=list)
    products_specs_changed: list[int] = field(default_factory=list)
    products_deleted: list[int] = field(default_factory=list)
    orphans_kept: list[int] = field(default_factory=list)  # còn trong danh sách mua/cảnh báo

    @property
    def changed(self) -> bool:
        return bool(
            self.moves
            or self.products_created
            or self.products_renamed
            or self.products_specs_changed
            or self.products_deleted
        )


@dataclass
class _Target:
    """Sản phẩm đích: `product` là sản phẩm có sẵn được giữ, `None` là sản phẩm sẽ tạo."""

    key: int  # khóa tạm trong lượt: id sản phẩm giữ lại, hoặc số âm cho sản phẩm mới
    product: Product | None
    category: Category
    brand: str
    name: str  # tên chuẩn sẽ lưu
    match_name: str  # tên dùng để ghép: tính từ tiêu đề offer đầu theo luật hiện tại
    model_code: str | None
    specs: dict[str, Any]
    fixed: bool  # sản phẩm của offer ngoài phạm vi `site`: giữ nguyên tên, mã
    offers: list[tuple[Offer, SpecsExtraction]] = field(default_factory=list)

    def candidate(self) -> Candidate:
        return Candidate(self.key, self.match_name, self.model_code, self.specs)


@dataclass(frozen=True)
class _Assignment:
    offer: Offer
    target: _Target
    method: MatchMethod
    score: float | None


class RematchService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._offers = OfferRepository(session)
        self._products = ProductRepository(session)

    def run(
        self,
        categories: Sequence[Category] = REMATCH_CATEGORIES,
        *,
        site: SiteKey | None = None,
        apply: bool = False,
    ) -> RematchReport:
        """Ghép lại offer của `categories` (chỉ offer của `site` nếu có). `apply=False` chỉ tính,
        không ghi gì; `apply=True` ghi qua repository (chỉ `flush`, người gọi `commit`)."""
        report = RematchReport(applied=apply)
        for category in categories:
            self._run_category(category, site, apply, report)
        return report

    def _run_category(
        self, category: Category, site: SiteKey | None, apply: bool, report: RematchReport
    ) -> None:
        offers = self._offers.list_by_category(category)
        current = {
            p.id: p
            for p in self._products.get_many(sorted({o.product_id for o in offers}))
            if p.id is not None
        }
        targets: dict[int, _Target] = {}
        # Sản phẩm của offer ngoài phạm vi giữ nguyên: là ứng viên ghép, không bị đổi tên/mã.
        for offer in offers:
            if site is not None and offer.site is not site and offer.product_id not in targets:
                product = current[offer.product_id]
                targets[offer.product_id] = self._target_of(product, fixed=True)
        assignments: list[_Assignment] = []
        next_new = -1
        for offer in offers:
            if site is not None and offer.site is not site:
                continue
            report.offers_checked += 1
            extraction = extract_specs(category, offer.title, offer.raw_specs)
            brand = detect_brand(offer.title)
            own = current[offer.product_id]
            same_brand = own.brand == brand
            code = extract_model_code(category, offer.title)
            if category is Category.laptop and same_brand and own.model_code is not None:
                # Mã đang có (có thể từ MPN trang chi tiết, offer không lưu hint) thắng mã đọc từ
                # tên: giữ nguyên cách ghép theo mã của lần đầu.
                code = own.model_code
            # Sản phẩm hiện tại (thông số seed, LLM đã điền, trang chi tiết) chỉ bù trường trống.
            specs = merge_specs(category, extraction.specs, own.specs)
            name = canonical_name(offer.title, category)
            pool = [t.candidate() for t in targets.values() if t.brand == brand]
            decision = decide_match(category, brand, code, name, specs, pool)
            if decision.product_id is not None:
                target = targets[decision.product_id]
                if (
                    code is not None
                    and target.model_code is None
                    and not target.fixed
                    and not any(t.model_code == code and t.brand == brand for t in targets.values())
                ):
                    target.model_code = code
                target.specs = merge_specs(category, target.specs, specs)
                method, score = decision.method, decision.score
            else:
                kept = offer.product_id not in targets
                key = offer.product_id if kept else next_new
                if not kept:
                    next_new -= 1
                target = _Target(
                    key=key,
                    product=own if kept else None,
                    category=category,
                    brand=brand,
                    # Tên cũ giữ nguyên khi hãng không đổi (chỉ là chữ hiển thị; khóa tên luôn
                    # tính lại theo luật hiện tại khi ghép).
                    name=own.canonical_name if kept and same_brand else name,
                    match_name=name,
                    model_code=None if decision.code_taken else code,
                    specs=specs,
                    fixed=False,
                )
                targets[key] = target
                method, score = MatchMethod.new, None
            target.offers.append((offer, extraction))
            assignments.append(_Assignment(offer, target, method, score))
        self._report_and_apply(category, current, targets, assignments, apply, report)

    @staticmethod
    def _target_of(product: Product, *, fixed: bool) -> _Target:
        if product.id is None:  # pragma: no cover - sản phẩm đọc từ CSDL luôn có id
            raise RuntimeError("product without id")
        return _Target(
            key=product.id,
            product=product,
            category=product.category,
            brand=product.brand,
            name=product.canonical_name,
            match_name=product.canonical_name,
            model_code=product.model_code,
            specs=dict(product.specs),
            fixed=fixed,
        )

    def _report_and_apply(
        self,
        category: Category,
        current: dict[int, Product],
        targets: dict[int, _Target],
        assignments: list[_Assignment],
        apply: bool,
        report: RematchReport,
    ) -> None:
        for assignment in assignments:
            offer, target = assignment.offer, assignment.target
            if target.key != offer.product_id:
                report.moves.append(
                    OfferMove(
                        _offer_id(offer),
                        offer.title,
                        offer.product_id,
                        target.key if target.key > 0 else None,
                        assignment.method,
                    )
                )
        rebuilt = {key: _rebuild_specs(t) for key, t in targets.items() if not t.fixed}
        for key, target in targets.items():
            if target.fixed:
                continue
            if target.product is None:
                report.products_created += 1
                continue
            product = target.product
            if (product.brand, product.canonical_name, product.model_code) != (
                target.brand,
                target.name,
                target.model_code,
            ):
                report.products_renamed.append(key)
            if rebuilt[key] != product.specs:
                report.products_specs_changed.append(key)
        kept_ids = {t.key for t in targets.values()}
        orphans = [pid for pid in current if pid not in kept_ids]
        if not apply:
            for pid in orphans:
                referenced = self._products.is_referenced(pid, count_offers=False)
                (report.orphans_kept if referenced else report.products_deleted).append(pid)
            return
        self._apply(category, targets, assignments, rebuilt, [current[pid] for pid in orphans])
        for pid in orphans:
            product = current[pid]
            if self._products.is_referenced(pid):
                report.orphans_kept.append(pid)
            else:
                self._products.delete(product)
                report.products_deleted.append(pid)
        if report.moves or report.products_deleted:
            logger.info(
                "Ghép lại %s: chuyển %d offer, xóa %d sản phẩm",
                category,
                len(report.moves),
                len(report.products_deleted),
            )

    def _apply(
        self,
        category: Category,
        targets: dict[int, _Target],
        assignments: list[_Assignment],
        rebuilt: dict[int, dict[str, Any]],
        orphans: list[Product],
    ) -> None:
        own = [t for t in targets.values() if not t.fixed]
        # Pha 1: bỏ mã của sản phẩm sẽ đổi mã và của sản phẩm mồ côi (xóa sau cùng) để đặt lại
        # không va chỉ mục unique (category, brand, model_code) giữa chừng.
        clear = [
            t.product
            for t in own
            if t.product is not None
            and t.product.model_code is not None
            and (t.product.brand, t.product.model_code) != (t.brand, t.model_code)
        ]
        for product in [*clear, *(p for p in orphans if p.model_code is not None)]:
            self._products.set_identity(
                product, brand=product.brand, canonical_name=product.canonical_name, model_code=None
            )
        # Pha 2: đặt lại tên/mã, tạo sản phẩm mới, chuyển offer, dựng lại specs.
        for target in own:
            specs = rebuilt[target.key]
            if target.model_code is not None:
                holder = self._products.find_by_model_key(category, target.brand, target.model_code)
                if holder is not None and holder is not target.product:
                    # Mã thuộc sản phẩm ngoài lượt (không còn offer nào): không giành mã.
                    target.model_code = None
            if target.product is None:
                target.product = self._products.add(
                    Product(
                        category=category,
                        brand=target.brand,
                        model_code=target.model_code,
                        canonical_name=target.name,
                        specs=specs,
                        specs_confidence=specs_confidence(category, specs),
                    )
                )
                continue
            product = target.product
            if (product.brand, product.canonical_name, product.model_code) != (
                target.brand,
                target.name,
                target.model_code,
            ):
                self._products.set_identity(
                    product,
                    brand=target.brand,
                    canonical_name=target.name,
                    model_code=target.model_code,
                )
            if specs != product.specs:
                self._products.update_specs(product, specs, specs_confidence(category, specs))
        for assignment in assignments:
            owner = assignment.target.product
            if owner is None or owner.id is None:  # pragma: no cover - pha 2 đã tạo
                raise RuntimeError("target product was not created")
            if assignment.offer.product_id != owner.id:
                self._offers.reassign(
                    assignment.offer, owner.id, assignment.method, assignment.score
                )


def _offer_id(offer: Offer) -> int:
    if offer.id is None:  # pragma: no cover - offer đọc từ CSDL luôn có id
        raise RuntimeError("offer without id")
    return offer.id


def _rebuild_specs(target: _Target) -> dict[str, Any]:
    """Specs từ mọi offer của sản phẩm theo thứ tự nhãn bảng thông số > specs cũ của sản phẩm giữ
    lại > tiêu đề; cùng nguồn thì offer cũ thắng; giá trị đủ thay giá trị yếu ở mọi bước.

    Specs cũ đứng trên tiêu đề vì có thể chi tiết hơn (seed, LLM dự phòng, bảng thông số đã gộp)
    nhưng thua nhãn: đó chính là lỗi "giá trị cũ thắng" mà lượt ghép lại sửa."""
    category = target.category
    from_labels: dict[str, Any] = {}
    from_titles: dict[str, Any] = {}
    for _offer, extraction in sorted(target.offers, key=lambda pair: _offer_id(pair[0])):
        labels = {k: v for k, v in extraction.specs.items() if k in extraction.label_fields}
        titles = {k: v for k, v in extraction.specs.items() if k not in extraction.label_fields}
        from_labels = merge_specs(category, from_labels, labels)
        from_titles = merge_specs(category, from_titles, titles)
    specs = from_labels
    if target.product is not None:
        specs = merge_specs(category, specs, target.product.specs)
    return merge_specs(category, specs, from_titles)
