"""Lỗi miền (app/domain/errors.py) phải khớp bảng mã lỗi ở docs/07 §2."""

import re
from pathlib import Path

import pytest

from app.domain import errors
from app.domain.errors import AppError

API_SPEC = Path(__file__).resolve().parents[3] / "docs" / "07-api-spec.md"

# AGENT_HALLUCINATION / AGENT_STEP_LIMIT chỉ có trong sự kiện SSE `error` (không có HTTP status).
SSE_ONLY_CODES = {"AGENT_HALLUCINATION", "AGENT_STEP_LIMIT"}


def _documented_http_errors() -> dict[str, int]:
    """Đọc bảng '## 2. Mã lỗi' của docs/07: {mã: HTTP status}."""
    text = API_SPEC.read_text(encoding="utf-8")
    assert "## 2. Mã lỗi" in text, "docs/07 đổi tên mục '## 2. Mã lỗi': sửa lại bộ phân tích"
    section = text.split("## 2. Mã lỗi", 1)[1].split("\n## ", 1)[0]
    documented: dict[str, int] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[1].isdigit():
            continue
        for code in re.findall(r"`([A-Z_]+)`", cells[0]):
            assert code not in documented, f"mã {code} xuất hiện hai lần trong bảng 07 §2"
            documented[code] = int(cells[1])
    return documented


def _domain_errors() -> list[type[AppError]]:
    """Mọi lớp lỗi cụ thể, kể cả khi sau này có lớp trung gian (lớp không có `code`)."""
    found: list[type[AppError]] = []
    pending = list(AppError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if "code" in vars(cls):
            found.append(cls)
    return found


def test_domain_errors_match_the_http_error_table_in_the_api_spec() -> None:
    in_code = {cls.code: cls.status_code for cls in _domain_errors()}
    assert in_code == _documented_http_errors()


def test_sse_only_codes_are_not_http_domain_errors() -> None:
    assert SSE_ONLY_CODES.isdisjoint(cls.code for cls in _domain_errors())


def test_every_domain_error_has_a_unique_code_and_a_vietnamese_default_message() -> None:
    classes = _domain_errors()
    assert len({cls.code for cls in classes}) == len(classes)
    for cls in classes:
        assert cls.default_message.strip(), cls
        assert cls().message == cls.default_message


@pytest.mark.parametrize("cls", _domain_errors(), ids=lambda cls: cls.__name__)
def test_error_codes_are_upper_snake_case_and_status_is_an_http_error(
    cls: type[AppError],
) -> None:
    assert re.fullmatch(r"[A-Z]+(_[A-Z]+)*", cls.code)
    assert 400 <= cls.status_code <= 599


def test_message_and_details_can_be_overridden_per_instance() -> None:
    exc = errors.ProductNotFound("Không tìm thấy sản phẩm 999", details={"product_id": 999})
    assert exc.message == "Không tìm thấy sản phẩm 999"
    assert str(exc) == "Không tìm thấy sản phẩm 999"
    assert exc.details == {"product_id": 999}
    assert (exc.code, exc.status_code) == ("PRODUCT_NOT_FOUND", 404)


def test_details_is_a_fresh_dict_for_each_instance() -> None:
    first, second = errors.NotFound(), errors.NotFound()
    first.details["x"] = 1
    assert second.details == {}


def test_details_is_copied_so_later_changes_to_the_source_do_not_leak() -> None:
    source = {"a": 1}
    exc = errors.DuplicateAlert(details=source)
    source["a"] = 2
    assert exc.details == {"a": 1}
