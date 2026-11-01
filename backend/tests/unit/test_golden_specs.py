"""Golden trích xuất thông số (tests/unit/golden/{laptop,mouse,keyboard,headset}.yaml).

Tiêu đề lấy từ fixture thật của GearVN, An Phát, FPT Shop (docs/09 §3). Ngưỡng theo docs/11 T5.1:
≥ 40 ca laptop, ≥ 15 ca mỗi nhóm phụ kiện, độ chính xác trường bắt buộc ≥ 95%. T5.4 thêm recall
riêng từng trường (tỉ lệ giá trị kỳ vọng có thật được đọc đúng) và trường tùy chọn
`OPTIONAL_FIELDS`; trường tùy chọn chỉ được chấm ở ca có khóa đó trong `expect` (`null` = không
được điền, ví dụ "Plus V3 Switch" không có tên switch).
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
OPTIONAL_FIELDS: dict[Category, tuple[str, ...]] = {
    Category.laptop: ("screen_in",),
    Category.mouse: ("dpi_max",),  # chỉ trang chi tiết ghi DPI: mới có 3 ca
    Category.keyboard: ("form_factor", "switch_name"),
    Category.headset: (),
}
MIN_OPTIONAL_CASES = {"screen_in": 40, "dpi_max": 3, "form_factor": 30, "switch_name": 10}
# Recall đo được khi thêm (T5.4), không hạ. `form_factor`: "AKKO 5087" (87 phím = TKL) chưa đọc.
RECALL_FLOORS = {(Category.keyboard, "form_factor"): 0.94}


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


def _checked_fields(category: Category) -> tuple[str, ...]:
    return (*REQUIRED_FIELDS[category], *OPTIONAL_FIELDS[category])


def _recall(category: Category, cases: list[GoldenCase]) -> dict[str, tuple[int, int]]:
    """Theo trường: (số giá trị kỳ vọng có thật được đọc đúng, số giá trị kỳ vọng có thật)."""
    counts: dict[str, tuple[int, int]] = {}
    for case in cases:
        specs = extract_specs(category, case.title, case_raw_specs(case, category)).specs
        for name in _checked_fields(category):
            expected = case.expect.get(name)
            if expected is None:
                continue
            hit, total = counts.get(name, (0, 0))
            counts[name] = (hit + (specs.get(name) == expected), total + 1)
    return counts


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_recall_of_every_checked_field_meets_its_floor(
    name: str, category: Category, minimum: int, record_property: Any
) -> None:
    counts = _recall(category, load_cases(name))
    recall = {field: hit / total for field, (hit, total) in counts.items()}
    record_property("recall", {field: round(value, 4) for field, value in recall.items()})
    low = {
        field: value
        for field, value in recall.items()
        if value < RECALL_FLOORS.get((category, field), 1.0)
    }
    assert low == {}


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_optional_fields_have_enough_golden_cases(
    name: str, category: Category, minimum: int
) -> None:
    counts = _recall(category, load_cases(name))
    for field in OPTIONAL_FIELDS[category]:
        assert counts.get(field, (0, 0))[1] >= MIN_OPTIONAL_CASES[field], field


@pytest.mark.parametrize(("name", "category", "minimum"), GROUPS)
def test_optional_fields_never_contradict_a_golden_value(
    name: str, category: Category, minimum: int
) -> None:
    """Trường tùy chọn sai giá trị, hoặc được điền khi golden ghi `null`."""
    wrong: list[str] = []
    for case in load_cases(name):
        specs = extract_specs(category, case.title, case_raw_specs(case, category)).specs
        for field in OPTIONAL_FIELDS[category]:
            if field not in case.expect:
                continue
            actual, expected = specs.get(field), case.expect[field]
            if actual is not None and actual != expected:
                wrong.append(f"{case.id}.{field}: {actual!r} != {expected!r}")
    assert wrong == []
