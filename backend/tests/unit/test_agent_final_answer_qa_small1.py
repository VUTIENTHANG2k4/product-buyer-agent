"""QA small-1: `FinalAnswer.text` không được rỗng về mặt hiển thị (T6.11)."""

import pytest
from pydantic import ValidationError

from app.agent.schemas import FinalAnswer

NUL = chr(0)


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "   \n\t  ",
        NUL,
        NUL * 5,
        f" {NUL} {NUL}\n",
        " ",
        "  ",
        "　",
        "\r\n\r\n",
        "\x0b\x0c",
    ],
)
def test_blank_text_is_rejected(text: str) -> None:
    with pytest.raises(ValidationError, match="blank"):
        FinalAnswer(text=text)


@pytest.mark.parametrize(
    "text", ["Xin chào", " Có kết quả ", f"{NUL}Xin chào", "0", ".", " ok ", "😀"]
)
def test_visible_text_is_kept_as_is(text: str) -> None:
    assert FinalAnswer(text=text).text == text


def test_text_is_still_required_and_must_be_a_string() -> None:
    with pytest.raises(ValidationError):
        FinalAnswer.model_validate({})
    with pytest.raises(ValidationError):
        FinalAnswer.model_validate({"text": None})
    with pytest.raises(ValidationError):
        FinalAnswer.model_validate({"text": 5})


@pytest.mark.parametrize(
    "text",
    ["​", "﻿", "⁠", "­", "‎", " ​ ​ ", f"{NUL}​﻿"],
)
def test_text_made_only_of_invisible_format_characters_is_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        FinalAnswer(text=text)
