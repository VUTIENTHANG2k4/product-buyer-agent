"""Golden trích xuất thông số (tests/unit/golden/{laptop,mouse,keyboard,headset}.yaml).

Tiêu đề lấy từ fixture thật của GearVN, An Phát, FPT Shop (docs/09 §3). Ngưỡng theo docs/11 T5.1:
≥ 40 ca laptop, ≥ 15 ca mỗi nhóm phụ kiện, độ chính xác trường bắt buộc ≥ 95%.
"""

from typing import Any

import pytest

from app.domain.enums import Category
from app.normalize.extract import extract_specs
from app.normalize.specs import REQUIRED_FIELDS
from tests.golden_support import GoldenCase, case_raw_specs, fixture_items, load_cases

GROUPS = [
    ("laptop", Category.laptop, 40),
    ("mouse", Category.mouse, 15),
    ("keyboard", Category.keyboard, 15),
    ("headset", Category.headset, 15),
]
ACCURACY_FLOOR = 0.95


def _compare(case: GoldenCase, category: Category) -> tuple[int, int, list[str], list[str]]:
    """(số trường đúng, tổng, trường sai giá trị, trường mất so với kỳ vọng)."""
    result = extract_specs(category, case.title, case_raw_specs(case, category))
    correct = total = 0
    wrong: list[str] = []
    lost: list[str] = []
    for name in REQUIRED_FIELDS[category]:
        total += 1
        expected: Any = case.expect.get(name)
        actual: Any = result.specs.get(name)
        if actual == expected:
            correct += 1
        elif actual is not None:  # giá trị khác kỳ vọng, hoặc điền khi kỳ vọng là "không rõ"
            wrong.append(f"{case.id}.{name}: {actual!r} != {expected!r}")
        elif actual is None:
            lost.append(f"{case.id}.{name}: expected {expected!r}, got nothing")
    return correct, total, wrong, lost


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_golden_set_is_large_enough_with_unique_ids(
    name: str, category: Category, minimum: int
) -> None:
    cases = load_cases(name)
    assert len(cases) >= minimum
    assert len({case.id for case in cases}) == len(cases)
    assert len({(case.site, case.title) for case in cases if case.detail_fixture is None}) == len(
        [case for case in cases if case.detail_fixture is None]
    )


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_golden_titles_are_real_titles_from_the_fixtures(
    name: str, category: Category, minimum: int
) -> None:
    for case in load_cases(name):
        titles = fixture_items(case.site, case.fixture, category)
        assert case.title in titles, f"{case.id}: title not found in {case.fixture}"


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_golden_covers_every_site_that_sells_the_category(
    name: str, category: Category, minimum: int
) -> None:
    sites = {case.site.value for case in load_cases(name)}
    assert {"gearvn", "anphat", "fptshop"} <= sites


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_required_field_accuracy_meets_the_floor(
    name: str, category: Category, minimum: int, record_property: Any
) -> None:
    correct = total = 0
    wrong: list[str] = []
    lost: list[str] = []
    for case in load_cases(name):
        ok, count, bad, missing = _compare(case, category)
        correct, total = correct + ok, total + count
        wrong += bad
        lost += missing
    accuracy = correct / total
    record_property("accuracy", round(accuracy, 4))
    assert accuracy >= ACCURACY_FLOOR, f"{accuracy:.1%}: wrong={wrong} lost={lost}"


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_extractor_never_contradicts_a_golden_value(
    name: str, category: Category, minimum: int
) -> None:
    """Một giá trị sai (khác kỳ vọng có giá trị) tệ hơn một giá trị thiếu: không được có ca nào."""
    wrong: list[str] = []
    for case in load_cases(name):
        wrong += _compare(case, category)[2]
    assert wrong == []


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_extractor_does_not_lose_values_the_golden_expects(
    name: str, category: Category, minimum: int
) -> None:
    lost: list[str] = []
    for case in load_cases(name):
        lost += _compare(case, category)[3]
    assert lost == []
