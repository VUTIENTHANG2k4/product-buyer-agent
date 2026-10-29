"""Repository cho `ShoppingList` và `ShoppingListItem`."""

import unicodedata
from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from app.db.models import Offer, ShoppingList, ShoppingListItem
from app.db.repositories.ids import fits_int4
from app.domain.clock import utc_now


def normalize_list_name(name: str) -> str:
    """Tên danh sách ở dạng NFC: tên tiếng Việt gõ NFD (macOS, Telegram) vẫn khớp tên đã lưu."""
    return unicodedata.normalize("NFC", name)


class ShoppingListRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, name: str, *, now: datetime | None = None) -> ShoppingList:
        moment = now or utc_now()
        shopping_list = ShoppingList(
            name=normalize_list_name(name), created_at=moment, updated_at=moment
        )
        self._session.add(shopping_list)
        self._session.flush()
        return shopping_list

    def get(self, list_id: int) -> ShoppingList | None:
        return self._session.get(ShoppingList, list_id) if fits_int4(list_id) else None

    def get_by_name(self, name: str) -> ShoppingList | None:
        statement = (
            select(ShoppingList)
            .where(ShoppingList.name == normalize_list_name(name))
            .order_by(col(ShoppingList.id))
        )
        return self._session.exec(statement).first()

    def list_all(self) -> list[ShoppingList]:
        """Danh sách mua, cập nhật gần nhất trước."""
        statement = select(ShoppingList).order_by(
            col(ShoppingList.updated_at).desc(), col(ShoppingList.id).desc()
        )
        return list(self._session.exec(statement))

    def rename(
        self, shopping_list: ShoppingList, name: str, *, now: datetime | None = None
    ) -> ShoppingList:
        shopping_list.name = normalize_list_name(name)
        shopping_list.updated_at = now or utc_now()
        self._session.flush()
        return shopping_list

    def delete(self, shopping_list: ShoppingList) -> None:
        """Xóa danh sách; các mục bị xóa theo (`ON DELETE CASCADE`)."""
        self._session.delete(shopping_list)
        self._session.flush()
        self._session.expire_all()

    def list_items(self, list_id: int) -> list[ShoppingListItem]:
        """Các mục của danh sách theo thứ tự thêm."""
        statement = (
            select(ShoppingListItem)
            .where(ShoppingListItem.list_id == list_id)
            .order_by(col(ShoppingListItem.added_at), col(ShoppingListItem.id))
        )
        return list(self._session.exec(statement))

    def get_item(self, item_id: int) -> ShoppingListItem | None:
        return self._session.get(ShoppingListItem, item_id) if fits_int4(item_id) else None

    def add_item(
        self,
        list_id: int,
        product_id: int,
        *,
        quantity: int = 1,
        note: str | None = None,
        preferred_offer_id: int | None = None,
        price_at_add: int | None = None,
        now: datetime | None = None,
    ) -> ShoppingListItem:
        """Thêm sản phẩm vào danh sách; đã có thì cộng `quantity` (UNIQUE list_id, product_id).

        Mục đã có giữ `price_at_add` và `added_at` ban đầu; `note`/`preferred_offer_id` mới (nếu
        có) thay giá trị cũ. `quantity` phải ≥ 1. `preferred_offer_id` phải là offer của chính
        `product_id` (nếu không ném `ValueError`).
        """
        self._require_offer_of(product_id, preferred_offer_id)
        moment = now or utc_now()
        statement = insert(ShoppingListItem).values(
            list_id=list_id,
            product_id=product_id,
            quantity=quantity,
            note=note,
            preferred_offer_id=preferred_offer_id,
            price_at_add=price_at_add,
            added_at=moment,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            constraint="uq_shopping_list_item_list_id_product_id",
            set_={
                "quantity": col(ShoppingListItem.quantity) + excluded.quantity,
                "note": func.coalesce(excluded.note, col(ShoppingListItem.note)),
                "preferred_offer_id": func.coalesce(
                    excluded.preferred_offer_id, col(ShoppingListItem.preferred_offer_id)
                ),
            },
        )
        item: ShoppingListItem = self._session.exec(
            statement.returning(ShoppingListItem),
            execution_options={"populate_existing": True},
        ).scalar_one()
        self._touch(list_id, moment)
        self._session.flush()
        return item

    def update_item(
        self,
        item: ShoppingListItem,
        *,
        quantity: int | None = None,
        note: str | None = None,
        clear_note: bool = False,
        preferred_offer_id: int | None = None,
        clear_preferred_offer: bool = False,
        now: datetime | None = None,
    ) -> ShoppingListItem:
        """Đặt lại `quantity`, `note` và/hoặc offer ưu tiên (chỉ trường truyền vào); `clear_note`
        và `clear_preferred_offer` xóa giá trị. Offer ưu tiên phải thuộc sản phẩm của mục (nếu
        không ném `ValueError`, và không đổi gì).

        Chạm `updated_at` của list.
        """
        self._require_offer_of(item.product_id, preferred_offer_id)
        if quantity is not None:
            item.quantity = quantity
        if clear_preferred_offer:
            item.preferred_offer_id = None
        elif preferred_offer_id is not None:
            item.preferred_offer_id = preferred_offer_id
        if clear_note:
            item.note = None
        elif note is not None:
            item.note = note
        self._touch(item.list_id, now or utc_now())
        self._session.flush()
        return item

    def remove_item(self, item: ShoppingListItem, *, now: datetime | None = None) -> None:
        """Xóa mục khỏi danh sách và chạm `updated_at` của list."""
        list_id = item.list_id
        self._session.delete(item)
        self._touch(list_id, now or utc_now())
        self._session.flush()

    def _require_offer_of(self, product_id: int, offer_id: int | None) -> None:
        """`offer_id` (nếu có) phải là offer của `product_id`, nếu không ném `ValueError`."""
        if offer_id is None:
            return
        owner = (
            self._session.exec(select(Offer.product_id).where(Offer.id == offer_id)).first()
            if fits_int4(offer_id)
            else None
        )
        if owner != product_id:
            raise ValueError("preferred_offer_id không thuộc sản phẩm này")

    def _touch(self, list_id: int, moment: datetime) -> None:
        self._session.exec(
            update(ShoppingList).where(col(ShoppingList.id) == list_id).values(updated_at=moment)
        )
