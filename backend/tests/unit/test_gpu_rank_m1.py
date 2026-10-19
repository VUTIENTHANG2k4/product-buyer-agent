"""QA M1: chuỗi lạ, Unicode, dữ liệu cực trị cho `normalize_gpu_name`/`gpu_rank` (docs/04 §5.6)."""

import random
import time
import unicodedata

import pytest

from app.normalize.specs.gpu_rank import GPU_RANKS, gpu_rank, normalize_gpu_name
from app.normalize.specs.laptop import LaptopSpecs


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("RTX 4060", "RTX 4060", id="no-break-space"),
        pytest.param("RTX\t4060\n8GB", "RTX 4060", id="tab-and-newline"),
        pytest.param("RTX   4060", "RTX 4060", id="mixed-spaces"),
        pytest.param("RTX 4060™", "RTX 4060", id="trademark-glued"),
        pytest.param("RTX™4060", "RTX 4060", id="trademark-between"),
        pytest.param("GeForce®RTX™4060", "RTX 4060", id="registered-and-trademark"),
        pytest.param("NVIDIA GeForce RTX 4060 Laptop GPU (8GB GDDR6)", "RTX 4060", id="brackets"),
        pytest.param("(RTX 4060)", "RTX 4060", id="parenthesised"),
        pytest.param("RTX 4060, 8GB", "RTX 4060", id="comma"),
        pytest.param("RTX 4060/8GB", "RTX 4060", id="slash"),
        pytest.param("rtx_4060", "RTX 4060", id="underscore"),
        pytest.param("RTX - 4060", "RTX 4060", id="spaced-hyphen"),
        pytest.param("RTX 4070 TI SUPER", "RTX 4070 Ti Super", id="upper-case-suffixes"),
        pytest.param("RTX 5070TI", "RTX 5070 Ti", id="ti-glued"),
        pytest.param("GPU: RTX 4060 | RAM: 16GB", "RTX 4060", id="inside-spec-line"),
        pytest.param("İntegrated", "Integrated", id="dotted-capital-i"),
        pytest.param("INTEL UHD GRAPHICS", "Integrated", id="upper-case-integrated"),
        pytest.param("Intel UHD + Intel Iris Xe", "Integrated", id="two-integrated-names"),
    ],
)
def test_normalize_gpu_name_tolerates_whitespace_symbols_and_punctuation(
    raw: str, expected: str
) -> None:
    assert normalize_gpu_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("RTX​4060", id="zero-width-space"),
        pytest.param("rtx­4060", id="soft-hyphen"),
        pytest.param("RTX 4060M", id="mobile-suffix-not-in-grammar"),
        pytest.param("RTX 40608GB", id="digits-glued-to-vram"),
        pytest.param("RTX4060TIGER", id="glued-word"),
        pytest.param("XRTX 4060", id="prefix-glued"),
        pytest.param("RTX A2000", id="workstation-letter-model"),
        pytest.param("🙂", id="emoji-only"),
        pytest.param("\x00", id="nul"),
    ],
)
def test_normalize_gpu_name_returns_none_instead_of_guessing(raw: str) -> None:
    assert normalize_gpu_name(raw) is None
    assert gpu_rank(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("RTX ４０６０", id="fullwidth"),
        pytest.param("GeForce RTX ٤٠٦٠", id="arabic-indic"),
    ],
)
def test_normalize_gpu_name_returns_only_ascii_canonical_names(raw: str) -> None:
    name = normalize_gpu_name(raw)

    assert name is None or name.isascii()
    assert name is None or name == "RTX 4060"


def test_normalize_gpu_name_does_not_drop_letters_of_a_suffix() -> None:
    assert normalize_gpu_name("AMD Radeon RX 7900 XTX") == "RX 7900 XTX"
    assert normalize_gpu_name("amd radeon rx7900xtx") == "RX 7900 XTX"
    assert normalize_gpu_name("AMD Radeon RX 7900 XT") == "RX 7900 XT"


@pytest.mark.parametrize(
    "raw",
    [
        "GeForce RTX4060 8GB",
        "RTX 3050ti",
        "RTX 4070 Ti Super",
        "Radeon RX 7600M XT",
        "GTX 1650",
        "Onboard",
        "Apple M3 GPU",
        "RTX 5070 Ti Laptop",
    ],
)
def test_normalize_gpu_name_is_idempotent(raw: str) -> None:
    once = normalize_gpu_name(raw)

    assert once is not None
    assert normalize_gpu_name(once) == once
    assert gpu_rank(once) == gpu_rank(raw)


@pytest.mark.parametrize(
    "form",
    ["NFC", "NFD", "NFKC", "NFKD"],
)
def test_unicode_form_of_the_input_does_not_change_the_result(form: str) -> None:
    raw = "NVIDIA® GeForce RTX™ 4060 Laptop GPU – Đồ họa rời"

    assert normalize_gpu_name(unicodedata.normalize(form, raw)) == "RTX 4060"


def test_gpu_rank_of_every_known_name_survives_case_and_spacing_noise() -> None:
    for name, rank in GPU_RANKS.items():
        if name == "Integrated":
            continue
        noisy = name.lower().replace(" ", "")
        assert gpu_rank(noisy) == rank, noisy
        assert gpu_rank(f"  GeForce {name.upper()} 8GB  ") == rank, name


def test_normalize_gpu_name_never_raises_on_random_unicode() -> None:
    rng = random.Random(20261017)
    alphabet = (
        list("RTXrtxGgForceRadeonIntegrated0123456789 -_/()™® ​\n\t")
        + list("ÀÁÂÃĐĩũơưẠẢẤẦẨẪẬ̣̀́̃̉")
        + ["\U0001f600", "\u0000", "４", "٤", "‮", "﻿"]
    )
    for _ in range(3000):
        text = "".join(rng.choices(alphabet, k=rng.randint(0, 60)))

        name = normalize_gpu_name(text)

        assert name is None or (isinstance(name, str) and name.strip() == name and name)
        rank = gpu_rank(text)
        assert rank is None or rank in GPU_RANKS.values()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("RTX 4060" + " " * 300_000 + "x", id="long-spaces-after-number"),
        pytest.param("rtx " * 100_000, id="many-rtx-tokens"),
        pytest.param("RTX 4060" + " ti" * 100_000 + "x", id="repeated-ti"),
        pytest.param("RTX 4060 " * 50_000 + "TIx", id="repeated-valid-names-then-junk"),
        pytest.param("radeon " + " " * 300_000 + "x", id="long-spaces-after-radeon"),
        pytest.param("a" * 1_000_000 + " RTX 4060", id="megabyte-then-gpu"),
    ],
)
def test_normalize_gpu_name_runs_in_linear_time_on_hostile_input(text: str) -> None:
    started = time.perf_counter()

    normalize_gpu_name(text)

    assert time.perf_counter() - started < 3.0


def test_laptop_specs_keep_unrecognised_gpu_text_verbatim_with_null_rank_and_nfd_vietnamese() -> (
    None
):
    nfd = unicodedata.normalize("NFD", "Đồ họa tích hợp thế hệ mới")

    specs = LaptopSpecs(gpu_model=nfd)

    assert specs.gpu_model == nfd
    assert specs.gpu_rank is None
    assert specs.model_dump(mode="json")["gpu_rank"] is None


def test_laptop_specs_ambiguous_gpu_is_kept_raw_and_unranked_in_the_json_dump() -> None:
    specs = LaptopSpecs(gpu_model="RTX 4050 (up to RTX 4060)")

    dumped = specs.model_dump(mode="json")

    assert dumped["gpu_model"] == "RTX 4050 (up to RTX 4060)"
    assert dumped["gpu_rank"] is None


def test_fullwidth_digits_and_nfkc_trademark_text_resolve_to_the_canonical_name() -> None:
    assert normalize_gpu_name("RTX ４０６０") == "RTX 4060"
    assert normalize_gpu_name("GeForce RTXTM4060") == "RTX 4060"
    assert (
        gpu_rank("ＮＶＩＤＩＡ ＧｅＦｏｒｃｅ ＲＴＸ™ ３０７０ Ｔｉ")
        == gpu_rank("RTX 3070 Ti")
        == 42
    )


def test_new_ranked_gpus_are_recognised_with_spacing_and_case_noise() -> None:
    assert gpu_rank("GeForce RTX3070 8GB") == 38
    assert gpu_rank("rtx 3070ti") == 42
    assert gpu_rank("NVIDIA GeForce RTX 3080 Laptop GPU 16GB") == 52
