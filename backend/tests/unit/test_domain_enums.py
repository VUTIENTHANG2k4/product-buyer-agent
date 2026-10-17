"""Enum miền (app/domain/enums.py) phải khớp bảng enum ở docs/04 §4."""

import re
from enum import StrEnum
from pathlib import Path

import pytest

from app.domain import enums

DATA_MODEL = Path(__file__).resolve().parents[3] / "docs" / "04-data-model.md"
SECTION_TITLE = "## 4. Enum"


def _documented_enums() -> dict[str, list[str]]:
    """Đọc bảng '## 4. Enum' của docs/04: {tên enum: [giá trị]}."""
    text = DATA_MODEL.read_text(encoding="utf-8")
    assert SECTION_TITLE in text, "docs/04 đổi tên mục '## 4. Enum': sửa lại bộ phân tích"
    section = text.split(SECTION_TITLE, 1)[1].split("\n## ", 1)[0]
    documented: dict[str, list[str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or not line.lstrip().startswith("|"):
            continue
        name = re.fullmatch(r"`(\w+)`", cells[0])
        if name is None:
            continue
        assert name.group(1) not in documented, f"enum {name.group(1)} xuất hiện hai lần"
        documented[name.group(1)] = re.findall(r"`(\w+)`", cells[1])
    return documented


def _code_enums() -> dict[str, type[StrEnum]]:
    return {
        name: obj
        for name, obj in vars(enums).items()
        if isinstance(obj, type) and issubclass(obj, StrEnum) and obj is not StrEnum
    }


def test_documented_table_was_parsed() -> None:
    assert len(_documented_enums()) == 11


def test_code_and_docs_define_the_same_enums() -> None:
    assert set(_code_enums()) == set(_documented_enums())


@pytest.mark.parametrize("name", sorted(_documented_enums()))
def test_enum_values_match_documented_table(name: str) -> None:
    expected = _documented_enums()[name]
    actual = [member.value for member in _code_enums()[name]]
    assert actual == expected


def test_enum_member_is_its_plain_string() -> None:
    assert enums.Category.laptop == "laptop"
    assert str(enums.Category.laptop) == "laptop"
    assert enums.ScrapeStatus.NEEDS_HUMAN == "NEEDS_HUMAN"


def test_enum_parses_from_string() -> None:
    assert enums.SiteKey("gearvn") is enums.SiteKey.gearvn


@pytest.mark.parametrize(
    ("enum_cls", "bad_value"),
    [
        (enums.Category, "Laptop"),
        (enums.SiteKey, "shopee"),
        (enums.PriceType, ""),
        (enums.StockStatus, "in stock"),
        (enums.ScrapeStatus, "succeeded"),
        (enums.ScrapeTrigger, "cron"),
        (enums.MatchMethod, "exact"),
        (enums.AlertChannel, "sms"),
        (enums.AlertStatus, "deleted"),
        (enums.AgentRunStatus, "RUNNING"),
        (enums.MessageRole, "tool"),
    ],
)
def test_enum_rejects_unknown_value(enum_cls: type[StrEnum], bad_value: str) -> None:
    with pytest.raises(ValueError):
        enum_cls(bad_value)
