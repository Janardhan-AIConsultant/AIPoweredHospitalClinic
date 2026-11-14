import json
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.ai.llm import GrokLLM, Message, MockLLM, ToolCall, build_llm, parse_date, parse_time
from app.ai.proposals import create_proposal, read_proposal
from app.core.config import Settings
from app.core.exceptions import ExternalServiceError, RateLimitError, ValidationFailure
from app.core.rate_limit import RateLimiter
from app.schemas.chat import ChatRequest, ConfirmRequest

SETTINGS = Settings(_env_file=None, jwt_secret_key="k" * 40)


# ------------------------------------------------------------- parsing helpers
def test_parse_time_variants():
    assert parse_time("at 10am please") == "10:00"
    assert parse_time("3:30 PM") == "15:30"
    assert parse_time("12 am") == "00:00"
    assert parse_time("14:15") == "14:15"
    assert parse_time("no time here") is None
    assert parse_time("25:99") is None


def test_parse_date_variants():
    today = date(2030, 1, 1)  # Tuesday
    assert parse_date("tomorrow", today) == "2030-01-02"
    assert parse_date("day after tomorrow", today) == "2030-01-03"
    assert parse_date("today", today) == "2030-01-01"
    assert parse_date("on Monday", today) == "2030-01-07"
    assert parse_date("on tuesday", today) == "2030-01-08"  # same weekday -> next week
    assert parse_date("2030-02-03 please", today) == "2030-02-03"
    assert parse_date("whenever", today) is None


# ------------------------------------------------------------------ mock LLM
async def test_mock_llm_requests_tools_then_answers():
    llm = MockLLM(today=date(2030, 1, 1))
    first = await llm.complete([Message("user", "which specialties do you have")], [])
    assert first.tool_calls[0].name == "list_specializations"
    done = await llm.complete(
        [
            Message("user", "which specialties do you have"),
            Message("tool", json.dumps({"specializations": [{"name": "Cardiologist"}]}), name="list_specializations"),
        ],
        [],
    )
    assert "Cardiologist" in done.content and not done.tool_calls


async def test_mock_llm_smalltalk_and_tool_error():
    llm = MockLLM(today=date(2030, 1, 1))
    assert "Hello" in (await llm.complete([Message("user", "hello")], [])).content
    assert "help with" in (await llm.complete([Message("user", "banana")], [])).content
    err = await llm.complete([Message("user", "x"), Message("tool", json.dumps({"error": "nope"}), name="t")], [])
    assert "nope" in err.content
    bad = await llm.complete([Message("user", "x"), Message("tool", "not json", name="t")], [])
    assert "went wrong" in bad.content


# ---------------------------------------------------------------- Grok adapter
class FakeChat:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.bound, self.seen = reply, error, None, None

    def bind_tools(self, tools, **kwargs):
        self.bound = (tools, kwargs)
        return self

    async def ainvoke(self, messages):
        self.seen = messages
        if self.error:
            raise self.error
        return self.reply


def grok(fake: FakeChat) -> GrokLLM:
    return GrokLLM(Settings(_env_file=None, xai_api_key="sk-secret-key", xai_model="grok-test"), model=fake)


async def test_grok_converts_messages_and_parses_tool_calls():
    fake = FakeChat(
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "find_doctors", "args": {"name": "anil"}, "type": "tool_call"}],
        )
    )
    history = [
        Message("system", "sys"),
        Message("user", "hi"),
        Message("assistant", "", tool_calls=(ToolCall("c0", "list_specializations", {}),)),
        Message("tool", "{}", tool_call_id="c0", name="list_specializations"),
    ]
    out = await grok(fake).complete(history, [{"type": "function", "function": {"name": "x"}}])
    assert out.tool_calls == (ToolCall("c1", "find_doctors", {"name": "anil"}),)
    kinds = [type(m).__name__ for m in fake.seen]
    assert kinds == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage"]
    assert fake.seen[2].tool_calls[0]["name"] == "list_specializations"
    assert fake.seen[3].tool_call_id == "c0"
    assert fake.bound[1] == {"tool_choice": "auto"}


async def test_grok_text_reply_and_error_hiding():
    plain = FakeChat(AIMessage(content=[{"type": "text", "text": "Hi there"}]))
    assert (await grok(plain).complete([Message("user", "hi")], [])).content == "Hi there"
    assert plain.bound is None  # no tools -> no binding

    with pytest.raises(ExternalServiceError) as e:
        await grok(FakeChat(error=RuntimeError("sk-secret-key leaked"))).complete([Message("user", "hi")], [])
    assert "sk-secret-key" not in str(e.value)


def test_grok_builds_real_langchain_client_without_network():
    s = Settings(_env_file=None, xai_api_key="sk-secret-key", xai_model="grok-test")
    assert type(GrokLLM(s)._model).__name__ == "ChatXAI"


def test_build_llm_chooses_by_credentials():
    assert isinstance(build_llm(Settings(_env_file=None)), MockLLM)
    live = Settings(_env_file=None, xai_api_key="k", xai_model="m")
    assert isinstance(build_llm(live), GrokLLM)


# ------------------------------------------------------------------- proposals
def test_proposal_roundtrip():
    doctor = uuid.uuid4()
    claims = read_proposal(SETTINGS, create_proposal(SETTINGS, doctor, date(2030, 1, 2), time(10, 0)))
    assert claims["doctor_id"] == doctor and claims["date"] == date(2030, 1, 2) and claims["start_time"] == time(10)


def test_proposal_rejects_tamper_expiry_wrong_key_and_type():
    token = create_proposal(SETTINGS, uuid.uuid4(), date(2030, 1, 2), time(10))
    with pytest.raises(ValidationFailure):
        read_proposal(SETTINGS, token[:-3] + "abc")
    with pytest.raises(ValidationFailure):
        read_proposal(Settings(_env_file=None, jwt_secret_key="z" * 40), token)
    old = datetime.now(UTC) - timedelta(minutes=30)
    with pytest.raises(ValidationFailure):
        read_proposal(SETTINGS, create_proposal(SETTINGS, uuid.uuid4(), date(2030, 1, 2), time(10), now=old))
    with pytest.raises(ValidationFailure):
        read_proposal(SETTINGS, "garbage")

    from app.core.security import create_access_token  # a login token must not work as a proposal

    with pytest.raises(ValidationFailure):
        read_proposal(SETTINGS, create_access_token(SETTINGS, "u", "ADMIN"))


def test_proposal_requires_real_secret():
    with pytest.raises(RuntimeError):
        create_proposal(Settings(_env_file=None), uuid.uuid4(), date(2030, 1, 2), time(10))


# ---------------------------------------------------------------- rate limiter
def test_rate_limiter_window_and_isolation():
    now = [0.0]
    rl = RateLimiter(limit=3, window_seconds=10, clock=lambda: now[0])
    for _ in range(3):
        rl.check("a")
    with pytest.raises(RateLimitError):
        rl.check("a")
    rl.check("b")  # other clients unaffected
    now[0] = 10.5
    rl.check("a")  # window slid


# --------------------------------------------------------------------- schemas
def test_chat_request_rules():
    ok = ChatRequest.model_validate({"messages": [{"role": "user", "content": "hi"}]})
    assert ok.messages[0].role == "user"
    for bad in (
        {"messages": []},
        {"messages": [{"role": "system", "content": "x"}]},  # clients cannot send system messages
        {"messages": [{"role": "tool", "content": "x"}]},
        {"messages": [{"role": "assistant", "content": "x"}]},  # last must be user
        {"messages": [{"role": "user", "content": "a" * 501}]},
        {"messages": [{"role": "user", "content": ""}]},
        {"messages": [{"role": "user", "content": "   "}]},
    ):
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(bad)
    long = [{"role": "user", "content": "x" * 450}] * 10
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": long})


def test_confirm_request_validation():
    base = {"proposal_token": "t" * 30, "patient_name": " Asha  Rao ", "phone": "9876543210"}
    assert ConfirmRequest.model_validate(base).patient_name == "Asha Rao"
    with pytest.raises(ValidationError):
        ConfirmRequest.model_validate({**base, "email": "bad"})
    with pytest.raises(ValidationError):
        ConfirmRequest.model_validate({**base, "proposal_token": "short"})
