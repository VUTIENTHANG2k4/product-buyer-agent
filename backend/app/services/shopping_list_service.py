"""Danh sách mua (docs/07 §3.4, tool `add_to_shopping_list`).

Giá hiện tại của mục là giá hiệu lực của offer ưu tiên nếu còn mua được, nếu không là giá thấp
nhất còn mua được của sản phẩm. Trùng sản phẩm trong cùng danh sách thì cộng dồn số lượng.
"""

import unicodedata

from sqlmodel import Session

from app.db.models import Offer, ShoppingList, ShoppingListItem, utc_now
from app.db.repositories import (
    OfferRepository,
    ProductRepository,
    ShoppingListRepository,
    effective_price_of,
    normalize_list_name,
)
from app.domain.catalog import (
    MAX_QUANTITY,
    ShoppingListDetail,
    ShoppingListItemView,
    ShoppingListSummary,
)
from app.domain.errors import ListNotFound, ProductNotFound, ValidationFailed
from app.services.views import Clock, aware_now, sellable, to_offer_view

MAX_NAME_LENGTH = 100
MAX_NOTE_LENGTH = 500
DEFAULT_LIST_NAME = "Danh sách mua"


def _visible(text: str) -> bool:
    """Có ít nhất một ký tự nhìn thấy được (không phải khoảng trắng hay ký tự định dạng vô hình)."""
    return any(not ch.isspace() and unicodedata.category(ch) != "Cf" for ch in text)


def _clean_name(name: str) -> str:
    cleaned = " ".join(normalize_list_name(name).split())
    if not _visible(cleaned) or len(cleaned) > MAX_NAME_LENGTH or "\x00" in cleaned:
        raise ValidationFailed(f"Tên danh sách phải dài 1–{MAX_NAME_LENGTH} ký tự, không rỗng")
    return cleaned


def _check_quantity(quantity: int) -> None:
    if not 1 <= quantity <= MAX_QUANTITY:
        raise ValidationFailed(
            f"Số lượng phải trong khoảng 1..{MAX_QUANTITY}", details={"quantity": quantity}
        )


def _check_note(note: str | None) -> None:
    if note is not None and (len(note) > MAX_NOTE_LENGTH or "\x00" in note):
        raise ValidationFailed(f"Ghi chú tối đa {MAX_NOTE_LENGTH} ký tự, không chứa ký tự NUL")


class ShoppingListService:
    def __init__(self, session: Session, *, now: Clock = utc_now) -> None:
        self._now = now
        self._lists = ShoppingListRepository(session)
        self._products = ProductRepository(session)
        self._offers = OfferRepository(session)

    # ---- danh sách ----
    def create_list(self, name: str) -> ShoppingListSummary:
        created = self._lists.create(_clean_name(name), now=aware_now(self._now))
        return self._summary(created)

    def get_or_create(self, name: str | None = None) -> ShoppingListSummary:
        """Danh sách tên `name` (mặc định "Danh sách mua"); chưa có thì tạo. Dùng cho agent."""
        cleaned = _clean_name(name or DEFAULT_LIST_NAME)
        found = self._lists.get_by_name(cleaned)
        return self._summary(found or self._lists.create(cleaned, now=aware_now(self._now)))

    def list_lists(self) -> list[ShoppingListSummary]:
        return [self._summary(shopping_list) for shopping_list in self._lists.list_all()]

    def get_list(self, list_id: int) -> ShoppingListDetail:
        shopping_list = self._require_list(list_id)
        items = self._lists.list_items(list_id)
        views = self._item_views(items)
        return ShoppingListDetail(**self._summary(shopping_list, views).model_dump(), items=views)

    def rename_list(self, list_id: int, name: str) -> ShoppingListSummary:
        renamed = self._lists.rename(
            self._require_list(list_id), _clean_name(name), now=aware_now(self._now)
        )
        return self._summary(renamed)

    def delete_list(self, list_id: int) -> None:
        self._lists.delete(self._require_list(list_id))

    # ---- mục ----
    def add_item(
        self,
        list_id: int,
        product_id: int,
        *,
        quantity: int = 1,
        note: str | None = None,
        preferred_offer_id: int | None = None,
    ) -> ShoppingListItemView:
        """Thêm sản phẩm; đã có thì cộng `quantity` (giữ giá lúc thêm đầu tiên)."""
        self._require_list(list_id)
        _check_quantity(quantity)
        _check_note(note)
        if self._products.get(product_id) is None:
            raise ProductNotFound(details={"product_id": product_id})
        offers = self._offers.list_for_products([product_id])[product_id]
        existing = next(
            (item for item in self._lists.list_items(list_id) if item.product_id == product_id),
            None,
        )
        if existing is not None:
            _check_quantity(existing.quantity + quantity)
        try:
            item = self._lists.add_item(
                list_id,
                product_id,
                quantity=quantity,
                note=note,
                preferred_offer_id=preferred_offer_id,
                price_at_add=self._current_price(offers, preferred_offer_id),
                now=aware_now(self._now),
            )
        except ValueError as error:
            raise ValidationFailed(
                "Offer ưu tiên không thuộc sản phẩm này",
                details={"preferred_offer_id": preferred_offer_id},
            ) from error
        return self._item_views([item])[0]

    def update_item(
        self,
        list_id: int,
        item_id: int,
        *,
        quantity: int | None = None,
        note: str | None = None,
        clear_note: bool = False,
    ) -> ShoppingListItemView:
        item = self._require_item(list_id, item_id)
        if quantity is not None:
            _check_quantity(quantity)
        _check_note(note)
        updated = self._lists.update_item(
            item, quantity=quantity, note=note, clear_note=clear_note, now=aware_now(self._now)
        )
        return self._item_views([updated])[0]

    def remove_item(self, list_id: int, item_id: int) -> None:
        self._lists.remove_item(self._require_item(list_id, item_id), now=aware_now(self._now))

    # ---- nội bộ ----
    def _require_list(self, list_id: int) -> ShoppingList:
        found = self._lists.get(list_id)
        if found is None:
            raise ListNotFound(details={"list_id": list_id})
        return found

    def _require_item(self, list_id: int, item_id: int) -> ShoppingListItem:
        self._require_list(list_id)
        item = self._lists.get_item(item_id)
        if item is None or item.list_id != list_id:
            raise ListNotFound("Không tìm thấy mục trong danh sách", details={"item_id": item_id})
        return item

    @staticmethod
    def _current_price(offers: list[Offer], preferred_offer_id: int | None = None) -> int | None:
        buyable = sellable(offers)
        preferred = next((offer for offer in buyable if offer.id == preferred_offer_id), None)
        chosen = preferred or (buyable[0] if buyable else None)
        return None if chosen is None else effective_price_of(chosen)

    def _item_views(self, items: list[ShoppingListItem]) -> list[ShoppingListItemView]:
        product_ids = list({item.product_id for item in items})
        offers_by_product = self._offers.list_for_products(product_ids)
        views: list[ShoppingListItemView] = []
        for item in items:
            product = self._products.get(item.product_id)
            if product is None or item.id is None:  # pragma: no cover - khóa ngoại bảo đảm
                continue
            offers = offers_by_product[item.product_id]
            buyable = sellable(offers)
            preferred = next((o for o in buyable if o.id == item.preferred_offer_id), None)
            best = preferred or (buyable[0] if buyable else None)
            current = None if best is None else effective_price_of(best)
            delta = (
                None
                if current is None or item.price_at_add is None
                else current - item.price_at_add
            )
            views.append(
                ShoppingListItemView(
                    item_id=item.id,
                    product_id=item.product_id,
                    name=product.canonical_name,
                    quantity=item.quantity,
                    note=item.note,
                    preferred_offer_id=item.preferred_offer_id,
                    price_at_add=item.price_at_add,
                    current_price=current,
                    price_delta=delta,
                    best_offer=None if best is None else to_offer_view(best),
                )
            )
        return views

    def _summary(
        self, shopping_list: ShoppingList, views: list[ShoppingListItemView] | None = None
    ) -> ShoppingListSummary:
        if shopping_list.id is None:  # pragma: no cover - đọc từ CSDL luôn có id
            raise RuntimeError("shopping list has no id")
        if views is None:
            views = self._item_views(self._lists.list_items(shopping_list.id))
        return ShoppingListSummary(
            list_id=shopping_list.id,
            name=shopping_list.name,
            item_count=len(views),
            total_price=sum(
                v.quantity * v.current_price for v in views if v.current_price is not None
            ),
            updated_at=shopping_list.updated_at,
        )
