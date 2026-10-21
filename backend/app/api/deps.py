"""Dependency dùng chung của các router."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from app.config import Settings, get_settings
from app.services import health_service
from app.services.alert_service import AlertService
from app.services.catalog_service import CatalogService
from app.services.compare_service import CompareService
from app.services.database import session_scope
from app.services.health_service import DbStatus
from app.services.shopping_list_service import ShoppingListService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db_status(settings: SettingsDep) -> DbStatus:
    """Trạng thái kết nối CSDL; test ghi đè dependency này."""
    return health_service.check_db(settings.database_url.get_secret_value())


DbStatusDep = Annotated[DbStatus, Depends(get_db_status)]


def get_session(settings: SettingsDep) -> Iterator[Session]:
    """Một session mỗi request; test ghi đè bằng session của fixture `db_session`."""
    with session_scope(settings.database_url.get_secret_value()) as session:
        yield session


# scope="function": commit chạy ngay sau hàm xử lý, TRƯỚC khi gửi response. Mặc định ("request")
# commit chạy sau khi response đã gửi nên client có thể đọc lại trước khi dữ liệu được lưu.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def get_catalog_service(session: SessionDep) -> CatalogService:
    return CatalogService(session)


def get_compare_service(session: SessionDep) -> CompareService:
    return CompareService(session)


CatalogServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]
CompareServiceDep = Annotated[CompareService, Depends(get_compare_service)]


def get_shopping_list_service(session: SessionDep) -> ShoppingListService:
    return ShoppingListService(session)


def get_alert_service(session: SessionDep, settings: SettingsDep) -> AlertService:
    return AlertService(session, settings)


ShoppingListServiceDep = Annotated[ShoppingListService, Depends(get_shopping_list_service)]
AlertServiceDep = Annotated[AlertService, Depends(get_alert_service)]
