"""Fixture cho test API: app thật, session `db_session` (rollback cuối test), đồng hồ cố định."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_catalog_service, get_compare_service, get_session
from app.config import Settings, get_settings
from app.main import create_app
from app.services.catalog_service import CatalogService
from app.services.compare_service import CompareService
from tests.service_support import clock, make_settings


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(db_session: Session, settings: Settings) -> Iterator[TestClient]:
    """Client dùng chung một session với test: dữ liệu test thêm vào thấy ngay qua API.

    `commit()` của code API chỉ giải phóng savepoint (xem fixture `db_session`) nên mọi thứ vẫn bị
    rollback khi test kết thúc.
    """
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_catalog_service] = lambda: CatalogService(db_session, now=clock)
    app.dependency_overrides[get_compare_service] = lambda: CompareService(db_session, now=clock)
    with TestClient(app) as test_client:
        yield test_client
