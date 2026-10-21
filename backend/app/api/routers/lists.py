"""Danh sách mua (docs/07 §3.4)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.api.deps import ShoppingListServiceDep
from app.api.errors import error_responses
from app.api.schemas import ItemCreate, ItemPatch, ListBody, ListsResponse
from app.domain.catalog import ShoppingListDetail, ShoppingListItemView, ShoppingListSummary

router = APIRouter(tags=["lists"])

ListId = Annotated[int, Path(description="Id danh sách; id không tồn tại hoặc ngoài miền → 404")]
ItemId = Annotated[int, Path(description="Id mục trong danh sách")]


@router.get("/lists", response_model=ListsResponse, summary="Các danh sách mua")
def list_lists(service: ShoppingListServiceDep) -> ListsResponse:
    return ListsResponse(items=service.list_lists())


@router.post(
    "/lists",
    response_model=ShoppingListSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo danh sách mua",
    responses=error_responses(422),
)
def create_list(body: ListBody, service: ShoppingListServiceDep) -> ShoppingListSummary:
    return service.create_list(body.name)


@router.get(
    "/lists/{list_id}",
    response_model=ShoppingListDetail,
    summary="Chi tiết danh sách: các mục, giá hiện tại và chênh lệch so với lúc thêm",
    responses=error_responses(404, 422),
)
def get_list(list_id: ListId, service: ShoppingListServiceDep) -> ShoppingListDetail:
    return service.get_list(list_id)


@router.patch(
    "/lists/{list_id}",
    response_model=ShoppingListSummary,
    summary="Đổi tên danh sách",
    responses=error_responses(404, 422),
)
def rename_list(
    list_id: ListId, body: ListBody, service: ShoppingListServiceDep
) -> ShoppingListSummary:
    return service.rename_list(list_id, body.name)


@router.delete(
    "/lists/{list_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa danh sách và các mục của nó",
    responses=error_responses(404, 422),
)
def delete_list(list_id: ListId, service: ShoppingListServiceDep) -> Response:
    service.delete_list(list_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/lists/{list_id}/items",
    response_model=ShoppingListItemView,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm sản phẩm vào danh sách (đã có thì cộng dồn số lượng)",
    responses=error_responses(404, 422),
)
def add_item(
    list_id: ListId, body: ItemCreate, service: ShoppingListServiceDep
) -> ShoppingListItemView:
    return service.add_item(
        list_id,
        body.product_id,
        quantity=body.quantity,
        note=body.note,
        preferred_offer_id=body.preferred_offer_id,
    )


@router.patch(
    "/lists/{list_id}/items/{item_id}",
    response_model=ShoppingListItemView,
    summary="Đổi số lượng, ghi chú hoặc offer ưu tiên của một mục",
    responses=error_responses(404, 422),
)
def update_item(
    list_id: ListId, item_id: ItemId, body: ItemPatch, service: ShoppingListServiceDep
) -> ShoppingListItemView:
    sent = body.model_fields_set
    return service.update_item(
        list_id,
        item_id,
        quantity=body.quantity,
        note=body.note,
        clear_note="note" in sent and body.note is None,
        preferred_offer_id=body.preferred_offer_id,
        clear_preferred_offer="preferred_offer_id" in sent and body.preferred_offer_id is None,
    )


@router.delete(
    "/lists/{list_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa một mục khỏi danh sách",
    responses=error_responses(404, 422),
)
def remove_item(list_id: ListId, item_id: ItemId, service: ShoppingListServiceDep) -> Response:
    service.remove_item(list_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
