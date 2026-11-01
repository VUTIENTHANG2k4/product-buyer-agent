"""Golden ghép mẫu (tests/unit/golden/pairs.yaml): nên ghép / không nên ghép, 0 ghép sai."""

from typing import Any

import pytest

from app.domain.enums import Category, MatchMethod
from app.normalize.brand import detect_brand
from app.normalize.extract import extract_specs
from app.normalize.matcher import Candidate, MatchDecision, decide_match
from app.normalize.model_code import extract_model_code
from app.normalize.names import canonical_name
from tests.golden_support import GoldenPair, PairSide, load_pairs, real_titles

PAIRS = load_pairs()


class Offer:
    """Một phía của cặp, đã qua chuẩn hóa như pipeline làm."""

    def __init__(self, category: Category, side: PairSide) -> None:
        raw = {} if side.synthetic_from_title else real_titles(side.site, category)[side.title]
        self.brand = detect_brand(side.title)
        self.name = canonical_name(side.title, category)
        self.code = extract_model_code(category, side.title)
        self.specs: dict[str, Any] = extract_specs(category, side.title, raw).specs


def decide(pair: GoldenPair, existing: Offer, incoming: Offer) -> MatchDecision:
    """Offer `incoming` đến khi `existing` đã là một Product (id 1)."""
    candidates = (
        [Candidate(1, existing.name, existing.code, existing.specs)]
        if existing.brand == incoming.brand  # pipeline chỉ lấy ứng viên cùng hãng
        else []
    )
    return decide_match(
        pair.category, incoming.brand, incoming.code, incoming.name, incoming.specs, candidates
    )


def test_there_are_enough_pairs_of_both_kinds() -> None:
    kinds = [pair.expect for pair in PAIRS]
    assert len(PAIRS) >= 30
    assert kinds.count("merge") >= 10 and kinds.count("separate") >= 10
    assert set(kinds) == {"merge", "separate"}
    assert len({pair.id for pair in PAIRS}) == len(PAIRS)


def test_every_category_has_pairs() -> None:
    assert {pair.category for pair in PAIRS} == {
        Category.laptop,
        Category.mouse,
        Category.keyboard,
        Category.headset,
    }


@pytest.mark.parametrize("pair", PAIRS, ids=lambda pair: pair.id)
def test_titles_are_real_or_derived_from_real_ones(pair: GoldenPair) -> None:
    for side in (pair.a, pair.b):
        site = side.synthetic_from_site or side.site
        real = side.synthetic_from_title or side.title
        assert real in real_titles(site, pair.category), f"{pair.id}: {real!r} not in {site}"


@pytest.mark.parametrize("pair", PAIRS, ids=lambda pair: pair.id)
def test_pair_is_decided_as_expected_in_both_directions(pair: GoldenPair) -> None:
    a, b = Offer(pair.category, pair.a), Offer(pair.category, pair.b)
    for existing, incoming in ((a, b), (b, a)):
        decision = decide(pair, existing, incoming)
        if pair.expect == "merge":
            assert decision.product_id == 1, f"{pair.id}: expected merge ({pair.why})"
            assert decision.method in {MatchMethod.model_code, MatchMethod.fuzzy}
            assert decision.score is not None and decision.score >= 0.9
        else:
            assert decision.product_id is None, f"{pair.id}: wrongly merged ({pair.why})"
            assert decision.method is MatchMethod.new and decision.score is None


def test_no_pair_marked_separate_is_ever_merged() -> None:
    wrong = [
        pair.id
        for pair in PAIRS
        if pair.expect == "separate"
        and decide(pair, Offer(pair.category, pair.a), Offer(pair.category, pair.b)).product_id
        is not None
    ]
    assert wrong == []


def test_laptops_with_the_same_code_merge_by_model_code() -> None:
    laptop_merges = [p for p in PAIRS if p.category is Category.laptop and p.expect == "merge"]
    assert laptop_merges
    for pair in laptop_merges:
        a, b = Offer(pair.category, pair.a), Offer(pair.category, pair.b)
        assert decide(pair, a, b).method is MatchMethod.model_code, pair.id


def test_colour_variants_merge_by_name_not_by_code() -> None:
    pair = next(p for p in PAIRS if p.id == "mouse-colour-pulsar-x2")
    a, b = Offer(pair.category, pair.a), Offer(pair.category, pair.b)
    decision = decide(pair, a, b)
    assert (a.code, b.code) == (None, None)
    assert decision.method is MatchMethod.fuzzy and decision.score == 1.0
