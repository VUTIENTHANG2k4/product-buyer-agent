"""T6.1: nhà máy model chat và ScriptedChatModel."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from app.agent.llm import LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS, TEMPERATURE, get_chat_model
from app.agent.testing import ScriptedChatModel, ScriptExhausted, tool_call_message
from app.config import Settings
from app.domain.errors import LlmUnavailable


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:5432/x",
        "scraper_user_agent": "test-agent/0.1",
    }
    return Settings.model_validate({**base, **overrides})


def test_fake_provider_returns_scripted_model() -> None:
    model = get_chat_model("planner", make_settings(llm_provider="fake"))
    assert isinstance(model, ScriptedChatModel)
    assert model.script == []


def test_gemini_provider_uses_configured_model_timeout_and_retry() -> None:
    settings = make_settings(
        llm_provider="gemini", google_api_key=SecretStr("k"), gemini_model="gemini-test"
    )
    model = get_chat_model("executor", settings)
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-test"
    assert model.temperature == TEMPERATURE["executor"] == 0.2
    assert model.timeout == LLM_TIMEOUT_SECONDS == 30.0
    assert model.max_retries == LLM_MAX_RETRIES == 1


def test_openai_provider_uses_configured_model() -> None:
    settings = make_settings(
        llm_provider="openai", openai_api_key=SecretStr("k"), openai_model="gpt-test"
    )
    model = get_chat_model("planner", settings)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-test"
    assert model.temperature == 0.0
    assert model.max_retries == 1


@pytest.mark.parametrize(
    ("provider", "variable"), [("gemini", "GOOGLE_API_KEY"), ("openai", "OPENAI_API_KEY")]
)
def test_missing_api_key_raises_llm_unavailable_naming_the_variable(
    provider: str, variable: str
) -> None:
    with pytest.raises(LlmUnavailable, match=variable):
        get_chat_model("planner", make_settings(llm_provider=provider))


@pytest.mark.parametrize(
    ("role", "temperature"), [("planner", 0.0), ("executor", 0.2), ("extractor", 0.0)]
)
def test_temperature_depends_on_role(role: str, temperature: float) -> None:
    settings = make_settings(llm_provider="gemini", google_api_key=SecretStr("k"))
    model = get_chat_model(role, settings)  # type: ignore[arg-type]
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.temperature == temperature


def test_scripted_model_plays_responses_in_order_and_records_calls() -> None:
    model = ScriptedChatModel(script=["một", AIMessage(content="hai")])
    assert model.invoke([HumanMessage(content="a")]).content == "một"
    assert model.invoke([HumanMessage(content="b")]).content == "hai"
    assert [call[0].content for call in model.calls] == ["a", "b"]


def test_scripted_model_emits_a_tool_call() -> None:
    @tool
    def search_catalog(category: str) -> str:
        """Tìm sản phẩm."""
        return category

    model = ScriptedChatModel(
        script=[tool_call_message("search_catalog", {"category": "laptop"}, "c1")]
    )
    bound = model.bind_tools([search_catalog])
    reply = bound.invoke("tìm laptop")
    assert isinstance(reply, AIMessage)
    assert reply.tool_calls == [
        {"name": "search_catalog", "args": {"category": "laptop"}, "id": "c1", "type": "tool_call"}
    ]
    assert model.bound_tool_names == ["search_catalog"]


def test_scripted_model_raises_when_script_is_exhausted() -> None:
    model = ScriptedChatModel(script=["chỉ một"])
    model.invoke("x")
    with pytest.raises(ScriptExhausted, match="1 phản hồi"):
        model.invoke("y")


def test_scripted_model_raises_an_exception_item() -> None:
    model = ScriptedChatModel(script=[TimeoutError("quá hạn")])
    with pytest.raises(TimeoutError, match="quá hạn"):
        model.invoke("x")


class Answer(BaseModel):
    text: str
    count: int


def test_structured_output_accepts_model_dict_and_json_text() -> None:
    model = ScriptedChatModel(
        script=[
            Answer(text="a", count=1),
            {"text": "b", "count": 2},
            AIMessage(content='{"text": "c", "count": 3}'),
        ]
    )
    structured = model.with_structured_output(Answer)
    results = [structured.invoke("q") for _ in range(3)]
    assert results == [
        Answer(text="a", count=1),
        Answer(text="b", count=2),
        Answer(text="c", count=3),
    ]


def test_structured_output_rejects_invalid_item() -> None:
    model = ScriptedChatModel(script=[{"text": "b", "count": "không phải số"}])
    with pytest.raises(ValueError, match="count"):
        model.with_structured_output(Answer).invoke("q")


def test_structured_output_and_plain_calls_share_one_script() -> None:
    model = ScriptedChatModel(script=[Answer(text="a", count=1), "xong"])
    assert model.with_structured_output(Answer).invoke("q") == Answer(text="a", count=1)
    assert model.invoke("q").content == "xong"
