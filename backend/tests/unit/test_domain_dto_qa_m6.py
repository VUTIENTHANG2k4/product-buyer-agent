"""QA M6: SpecFilter chặn chuỗi NUL và đầu vào quá dài (BUG-M6-8: NUL → PostgreSQL DataError)."""

import pytest
from pydantic import ValidationError

from app.domain.dto import SpecFilter

NUL = chr(0)


@pytest.mark.parametrize(
    "raw",
    [
        {"field": "gpu" + NUL, "op": "eq", "value": "RTX"},
        {"field": "gpu_model", "op": "eq", "value": "RTX" + NUL},
        {"field": "connection", "op": "contains", "value": NUL},
        {"field": "connection", "op": "in", "value": ["usb", "bt" + NUL]},
        {"field": "x" * 65, "op": "gte", "value": 1},
        {"field": "gpu_model", "op": "eq", "value": "y" * 201},
        {"field": "connection", "op": "in", "value": ["a"] * 51},
    ],
)
def test_hostile_spec_filter_text_is_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SpecFilter.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        {"field": "x" * 64, "op": "gte", "value": 1},
        {"field": "gpu_model", "op": "eq", "value": "y" * 200},
        {"field": "connection", "op": "in", "value": ["a"] * 50},
        {"field": "  gpu_rank  ", "op": "gte", "value": 40},
        {"field": "tên_trường", "op": "eq", "value": "Chuột Việt"},
    ],
)
def test_filters_at_the_limits_are_still_valid(raw: dict[str, object]) -> None:
    assert SpecFilter.model_validate(raw).field == str(raw["field"]).strip()
