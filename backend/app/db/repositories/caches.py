"""Repository cho hai bảng cache: kết quả LLM trích thông số và tìm kiếm trực tiếp tầng 2."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from app.db.models import LiveSearchCache, LlmExtractionCache
from app.domain.clock import utc_now
from app.domain.enums import Category


class LlmExtractionCacheRepository:
    """Khóa là SHA-256 của (category, title, raw_specs); kết quả không hết hạn."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, content_hash: str) -> LlmExtractionCache | None:
        return self._session.get(LlmExtractionCache, content_hash)

    def put(
        self,
        content_hash: str,
        category: Category,
        result: Mapping[str, Any],
        model: str,
        *,
        now: datetime | None = None,
    ) -> LlmExtractionCache:
        """Ghi hoặc thay kết quả của `content_hash` (`ON CONFLICT DO UPDATE`)."""
        statement = insert(LlmExtractionCache).values(
            content_hash=content_hash,
            category=category,
            result=dict(result),
            model=model,
            created_at=now or utc_now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=["content_hash"],
            set_={
                "category": statement.excluded.category,
                "result": statement.excluded.result,
                "model": statement.excluded.model,
                "created_at": statement.excluded.created_at,
            },
        )
        entry: LlmExtractionCache = self._session.exec(
            statement.returning(LlmExtractionCache),
            execution_options={"populate_existing": True},
        ).scalar_one()
        self._session.flush()
        return entry


class LiveSearchCacheRepository:
    """Khóa tìm kiếm → kết quả; hết hạn do người gọi quyết định qua `max_age` (6 giờ ở service)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(
        self, cache_key: str, *, max_age: timedelta, now: datetime | None = None
    ) -> LiveSearchCache | None:
        """Mục cache còn mới (`created_at` trong vòng `max_age` tính từ `now`), ngược lại None."""
        entry = self._session.get(LiveSearchCache, cache_key)
        if entry is None or (now or utc_now()) - entry.created_at > max_age:
            return None
        return entry

    def put(
        self,
        cache_key: str,
        results: Sequence[Mapping[str, Any]],
        *,
        now: datetime | None = None,
    ) -> LiveSearchCache:
        """Ghi hoặc thay kết quả của `cache_key` và làm mới `created_at`."""
        statement = insert(LiveSearchCache).values(
            cache_key=cache_key,
            results=[dict(item) for item in results],
            created_at=now or utc_now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={
                "results": statement.excluded.results,
                "created_at": statement.excluded.created_at,
            },
        )
        entry: LiveSearchCache = self._session.exec(
            statement.returning(LiveSearchCache),
            execution_options={"populate_existing": True},
        ).scalar_one()
        self._session.flush()
        return entry

    def purge_older_than(self, cutoff: datetime) -> int:
        """Xóa mục có `created_at` < `cutoff`; trả số mục đã xóa."""
        result = self._session.exec(
            delete(LiveSearchCache)
            .where(col(LiveSearchCache.created_at) < cutoff)
            .execution_options(synchronize_session="fetch")
        )
        self._session.flush()
        return int(result.rowcount)
