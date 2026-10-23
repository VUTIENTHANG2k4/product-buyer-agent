"""Nền chung của 8 tool agent (docs/05 §3, skill `agent-tool`).

Mỗi tool: tham số là một Pydantic model, thân chỉ gọi `app/services`, kết quả là dict nhỏ gọn
(≤ 4.000 ký tự JSON), không HTML thô. Lỗi nghiệp vụ trả `{"ok": false, "error", "message"}` để LLM
thử cách khác; lỗi hệ thống được ném lên cho executor ghi sự kiện `error`.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, TypeVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from app.config import Settings
from app.db.models import utc_now
from app.domain.errors import AppError
from app.services.live_search_service import LiveSearchService
from app.services.views import Clock

MAX_RESULT_CHARS: Final = 4_000
MAX_TEXT_CHARS: Final = 120  # tên/tiêu đề lấy từ web là dữ liệu: cắt ngắn trước khi đưa cho LLM

Result = dict[str, Any]
A = TypeVar("A", bound=BaseModel)


@dataclass(frozen=True)
class ToolContext:
    """Thứ tool cần: cách mở session (mỗi lần gọi một session), cấu hình, đồng hồ.

    `live_search` là service tìm trực tiếp tầng 2 (dùng chung Fetcher của API); `None` thì tool
    `live_search_other` báo chưa khả dụng thay vì tìm.
    """

    session_factory: Callable[[], Session]
    settings: Settings
    now: Clock = utc_now
    live_search: LiveSearchService | None = None


def clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    """Cắt chuỗi dài từ web, thêm "…" khi bị cắt."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def error_result(code: str, message: str) -> Result:
    return {"ok": False, "error": code, "message": message}


def size_of(result: Result) -> int:
    return len(json.dumps(result, ensure_ascii=False))


def limit_size(result: Result, list_keys: tuple[str, ...], limit: int = MAX_RESULT_CHARS) -> Result:
    """Bớt phần tử cuối của các danh sách trong `list_keys` đến khi JSON ≤ `limit` ký tự.

    Danh sách dài nhất được cắt trước; kết quả có `truncated: true` nếu đã bớt. Nếu hết danh sách
    để bớt mà vẫn quá lớn thì trả lỗi gọn thay vì một kết quả vượt giới hạn.
    """
    if size_of(result) <= limit:
        return result
    trimmed = dict(result)
    trimmed["truncated"] = True
    lists = {key: list(trimmed[key]) for key in list_keys if key in trimmed}
    trimmed.update(lists)
    while size_of(trimmed) > limit:
        longest = max(lists, key=lambda key: len(lists[key]), default=None)
        if longest is None or not lists[longest]:
            return error_result("RESULT_TOO_LARGE", "Kết quả quá lớn, hãy thu hẹp yêu cầu")
        lists[longest].pop()
        trimmed[longest] = lists[longest]
    return trimmed


def _validation_message(error: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(p) for p in item['loc']) or 'input'}: {item['msg']}"
        for item in error.errors()[:3]
    ]
    return json.dumps(error_result("VALIDATION_ERROR", "; ".join(parts)), ensure_ascii=False)


async def run_in_session(
    ctx: ToolContext, work: Callable[[Session], Result], *, write: bool = False
) -> Result:
    """Chạy `work` trong luồng riêng với một session mới (repo/service đồng bộ).

    Tool ghi (`write=True`) commit khi xong; mọi trường hợp lỗi đều rollback. `AppError` thành
    kết quả lỗi cho LLM, lỗi khác được ném tiếp.
    """

    def job() -> Result:
        with ctx.session_factory() as session:
            try:
                result = work(session)
                if write and result.get("ok", True):
                    session.commit()
                return result
            except AppError as error:
                session.rollback()
                return error_result(error.code, error.message)
            except Exception:
                session.rollback()
                raise

    return await asyncio.to_thread(job)


def make_tool(
    ctx: ToolContext,
    *,
    name: str,
    description: str,
    args_schema: type[A],
    handler: Callable[[ToolContext, A], Awaitable[Result]],
) -> StructuredTool:
    """Dựng `StructuredTool` bất đồng bộ: tham số sai kiểu/miền trả lỗi gọn cho LLM thử lại."""

    async def run(**kwargs: Any) -> Result:
        return await handler(ctx, args_schema.model_validate(kwargs))

    return StructuredTool.from_function(
        coroutine=run,
        name=name,
        description=description,
        args_schema=args_schema,
        handle_validation_error=_validation_message,
    )
