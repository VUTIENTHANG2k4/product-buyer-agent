"""Dependency dùng chung của các router."""

from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings
from app.services import health_service
from app.services.health_service import DbStatus

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db_status(settings: SettingsDep) -> DbStatus:
    """Trạng thái kết nối CSDL; test ghi đè dependency này."""
    return health_service.check_db(settings.database_url.get_secret_value())


DbStatusDep = Annotated[DbStatus, Depends(get_db_status)]
