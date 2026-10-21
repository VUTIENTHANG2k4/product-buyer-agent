"""Trường lọc theo khung thông số của từng nhóm và đọc `spec.<field>__<op>=<value>` (docs/07 §3.3).

Mô tả trường lấy từ JSON schema của model specs (`app.normalize.specs.SPEC_MODELS`), gồm cả trường
tính toán `gpu_rank`, nên danh sách lọc được không bao giờ lệch khung thông số.
"""

import re
from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any, Final

from pydantic import ValidationError

from app.domain.catalog import SpecFieldInfo, SpecKind
from app.domain.dto import MAX_FILTER_LIST, SpecFilter
from app.domain.enums import Category
from app.domain.errors import ValidationFailed
from app.normalize.specs import SPEC_MODELS

SPEC_PARAM_PREFIX: Final = "spec."
_OPS: Final[Mapping[SpecKind, tuple[str, ...]]] = {
    "integer": ("eq", "gte", "lte"),
    "number": ("eq", "gte", "lte"),
    "boolean": ("eq",),
    "string": ("eq", "in"),
    "list": ("contains", "contains_any"),
}
_JSON_KINDS: Final[Mapping[str, SpecKind]] = {
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
}
_INTEGER: Final = re.compile(r"-?\d{1,18}")
_NUMBER: Final = re.compile(r"-?\d{1,18}(?:\.\d{1,9})?")
_BOOLEANS: Final = {"true": True, "false": False}


def _choices(node: Mapping[str, Any], defs: Mapping[str, Any]) -> list[str] | None:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return None
    values = defs.get(ref.rsplit("/", 1)[-1], {}).get("enum")
    return [str(value) for value in values] if values else None


def _describe(name: str, schema: Mapping[str, Any], defs: Mapping[str, Any]) -> SpecFieldInfo:
    options = [o for o in schema.get("anyOf", [schema]) if o.get("type") != "null"]
    node: Mapping[str, Any] = options[0] if options else {}
    kind: SpecKind
    choices: list[str] | None
    if node.get("type") == "array":
        kind, choices = "list", _choices(node.get("items", {}), defs)
    else:
        choices = _choices(node, defs)
        kind = _JSON_KINDS.get(str(node.get("type")), "string")
    return SpecFieldInfo(name=name, kind=kind, ops=list(_OPS[kind]), choices=choices)


@cache
def spec_fields(category: Category) -> tuple[SpecFieldInfo, ...]:
    """Trường lọc được của nhóm (rỗng cho nhóm không có khung thông số, ví dụ `other`)."""
    model = SPEC_MODELS.get(category)
    if model is None:
        return ()
    schema = model.model_json_schema(mode="serialization")
    defs = schema.get("$defs", {})
    return tuple(_describe(name, node, defs) for name, node in schema["properties"].items())


def _split_param(key: str) -> tuple[str, str]:
    """`spec.gpu_rank__gte` → ("gpu_rank", "gte"); thiếu `__op` thì là `eq`."""
    field, _, op = key.removeprefix(SPEC_PARAM_PREFIX).partition("__")
    return field, op or "eq"


def _value(info: SpecFieldInfo, op: str, raw: str) -> bool | int | float | str | list[str]:
    if op in ("in", "contains_any"):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if not 1 <= len(parts) <= MAX_FILTER_LIST:
            raise ValidationFailed(
                f"spec.{info.name}: cần 1–{MAX_FILTER_LIST} giá trị, cách nhau bằng dấu phẩy"
            )
        return parts
    if info.kind == "boolean":
        if raw.lower() not in _BOOLEANS:
            raise ValidationFailed(f"spec.{info.name}: chỉ nhận true hoặc false")
        return _BOOLEANS[raw.lower()]
    if info.kind == "integer":
        if not _INTEGER.fullmatch(raw):
            raise ValidationFailed(f"spec.{info.name}: cần số nguyên")
        return int(raw)
    if info.kind == "number":
        if not _NUMBER.fullmatch(raw):
            raise ValidationFailed(f"spec.{info.name}: cần một số")
        number = float(raw)
        return int(number) if number.is_integer() else number
    return raw


def parse_spec_filters(
    params: Mapping[str, str] | Iterable[tuple[str, str]], category: Category | None
) -> list[SpecFilter]:
    """Bộ lọc từ các tham số `spec.<field>__<op>=<value>` (tham số khác bị bỏ qua).

    Cần `category` để biết khung thông số. Trường lạ, toán tử không hợp với kiểu trường hoặc giá trị
    sai kiểu/ngoài enum → `ValidationFailed` (422). Danh sách giá trị cho `in`/`contains_any` cách
    nhau bằng dấu phẩy.
    """
    pairs = params.items() if isinstance(params, Mapping) else params
    raw: dict[str, str] = {}
    for key, value in pairs:
        if not key.startswith(SPEC_PARAM_PREFIX):
            continue
        if key in raw:  # lặp lại sẽ làm mất ràng buộc đầu một cách im lặng
            raise ValidationFailed(f"Tham số {key[:100]} chỉ được dùng một lần")
        raw[key] = value
    if not raw:
        return []
    if category is None:
        raise ValidationFailed("Lọc theo spec.* cần có tham số category")
    known = {info.name: info for info in spec_fields(category)}
    filters: list[SpecFilter] = []
    for key, text in raw.items():
        field, op = _split_param(key)
        info = known.get(field)
        if info is None:
            raise ValidationFailed(
                f"Nhóm {category.value} không có trường lọc '{field[:64]}'",
                details={"param": key[:100], "fields": sorted(known)},
            )
        if op not in info.ops:
            raise ValidationFailed(
                f"spec.{field}: toán tử '{op[:20]}' không dùng được, chọn một trong {info.ops}",
                details={"param": key[:100]},
            )
        value = _value(info, op, text)
        if info.choices is not None:
            bad = [
                v for v in (value if isinstance(value, list) else [value]) if v not in info.choices
            ]
            if bad:
                raise ValidationFailed(
                    f"spec.{field}: giá trị không hợp lệ, chọn trong {info.choices}",
                    details={"param": key[:100]},
                )
        try:
            filters.append(SpecFilter.model_validate({"field": field, "op": op, "value": value}))
        except ValidationError as error:  # NUL, quá dài, số quá lớn...
            raise ValidationFailed(f"spec.{field}: giá trị không hợp lệ") from error
    return filters
