"""T5.3: lắp bộ LLM dự phòng và nạp prompt."""

import pytest
from pydantic import SecretStr

from app.agent.prompts import load_prompt
from app.agent.spec_filler import build_spec_filler
from app.config import Settings
from app.normalize.llm_extract import LlmSpecsFiller


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:5432/x",
        "scraper_user_agent": "test-agent/0.1",
    }
    return Settings.model_validate({**base, **overrides})


def test_extractor_prompt_exists_and_treats_web_text_as_data() -> None:
    prompt = load_prompt("extractor")
    assert "DỮ LIỆU" in prompt
    assert prompt == prompt.strip()


@pytest.mark.parametrize(
    "overrides",
    [
        {"llm_provider": "fake"},
        {"llm_provider": "gemini", "llm_extractor_enabled": False, "google_api_key": "k"},
        {"llm_provider": "gemini"},  # thiếu khóa API
    ],
)
def test_no_filler_when_fake_disabled_or_key_missing(overrides: dict[str, object]) -> None:
    assert build_spec_filler(make_settings(**overrides)) is None


def test_gemini_with_key_builds_an_enabled_filler() -> None:
    filler = build_spec_filler(
        make_settings(llm_provider="gemini", google_api_key=SecretStr("k"), gemini_model="g-1")
    )
    assert isinstance(filler, LlmSpecsFiller)
    assert filler.enabled
