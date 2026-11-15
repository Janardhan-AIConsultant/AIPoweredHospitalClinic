"""LLM abstraction: one interface, a deterministic mock and a Grok (xAI) adapter.

``MockLLM`` is used whenever xAI credentials are absent (``settings.llm_mode == "mock"``).
It speaks the same tool-calling protocol as the live model, so the whole agent loop,
tools and guardrails are exercised identically in both modes.

``GrokLLM`` calls xAI through LangChain (``langchain-xai``). It is tested with a fake
chat model only; it has NOT been run against the real API until a key is configured.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.config import Settings
from app.core.exceptions import ExternalServiceError
from app.utils.timezone import clinic_now


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class LLMClient(Protocol):
    async def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


# --------------------------------------------------------------------------- Grok
def _to_langchain(m: Message) -> BaseMessage:
    if m.role == "system":
        return SystemMessage(content=m.content)
    if m.role == "tool":
        return ToolMessage(content=m.content, tool_call_id=m.tool_call_id or "", name=m.name)
    if m.role == "assistant":
        return AIMessage(
            content=m.content,
            tool_calls=[{"id": c.id, "name": c.name, "args": c.arguments, "type": "tool_call"} for c in m.tool_calls],
        )
    return HumanMessage(content=m.content)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content if p)
    return ""


class GrokLLM:
    """Grok via LangChain's ``ChatXAI``. Pass ``model`` to inject a chat model (tests)."""

    def __init__(self, settings: Settings, model: Any | None = None) -> None:
        if model is None:
            from langchain_xai import ChatXAI

            model = ChatXAI(
                model=settings.xai_model,
                api_key=settings.xai_api_key,
                xai_api_base=settings.xai_base_url,
                temperature=0.2,
                max_tokens=400,
                timeout=settings.llm_timeout_seconds,
                max_retries=1,
            )
        self._model = model

    async def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        try:
            runnable = self._model.bind_tools(tools, tool_choice="auto") if tools else self._model
            out = await runnable.ainvoke([_to_langchain(m) for m in messages])
            calls = tuple(
                ToolCall(id=str(c["id"]), name=str(c["name"]), arguments=dict(c.get("args") or {}))
                for c in (out.tool_calls or [])
            )
            return LLMResponse(content=_text(out.content), tool_calls=calls)
        except Exception as exc:  # noqa: BLE001 - provider errors vary; never leak their text
            raise ExternalServiceError("The assistant is temporarily unavailable.") from exc


# --------------------------------------------------------------------------- Mock
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b", re.IGNORECASE)
_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DOCTOR_RE = re.compile(r"\bdr\.?\s+([a-z]+)", re.IGNORECASE)
_INFO_RE = re.compile(
    r"\b(hours?|opening|closing|timings?|open on|address|location|directions?|parking|payments?|pay|cancel\w*|"
    r"resched\w*|policy|policies|whatsapp|privacy|safe|account|language|bring|carry|arrive|sunday|holiday)\b",
    re.IGNORECASE,
)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_SPECIALTY_WORDS = {
    "cardio": "Cardiologist",
    "heart": "Cardiologist",
    "pediatric": "Pediatrician",
    "child": "Pediatrician",
    "kid": "Pediatrician",
    "derma": "Dermatologist",
    "skin": "Dermatologist",
    "ortho": "Orthopedic",
    "bone": "Orthopedic",
    "joint": "Orthopedic",
    "general": "General Physician",
    "physician": "General Physician",
    "fever": "General Physician",
}


def parse_time(text: str) -> str | None:
    """First time mentioned as 'HH:MM' (24h), or None."""
    m = _TIME_RE.search(text)
    if not m:
        return None
    if m.group(3):
        hour, minute, suffix = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    else:
        hour, minute = int(m.group(4)), int(m.group(5))
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else None


def parse_date(text: str, today: date) -> str | None:
    lowered = text.lower()
    if m := _ISO_RE.search(lowered):
        return m.group(1)
    if "day after tomorrow" in lowered:
        return (today + timedelta(days=2)).isoformat()
    if "tomorrow" in lowered:
        return (today + timedelta(days=1)).isoformat()
    if "today" in lowered:
        return today.isoformat()
    for i, name in enumerate(_WEEKDAYS):
        if name in lowered:
            delta = (i - today.weekday()) % 7 or 7
            return (today + timedelta(days=delta)).isoformat()
    return None


class MockLLM:
    """Deterministic, rule-based stand-in that follows the tool-calling protocol."""

    def __init__(self, today: date | None = None) -> None:
        self._today = today

    def _now(self) -> date:
        return self._today or clinic_now().date()

    async def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        text = messages[last_user].content if last_user >= 0 else ""
        results = [m for m in messages[last_user + 1 :] if m.role == "tool"]
        if results:
            return self._after_tools(text, results)
        return self._first_step(text, messages[:last_user])

    # -- step 1: decide which tool to call
    def _first_step(self, text: str, history: list[Message]) -> LLMResponse:
        lowered = text.lower()
        when, at = parse_date(text, self._now()), parse_time(text)
        doctor = _DOCTOR_RE.search(text)
        if not doctor:  # follow-up like "tomorrow at 10": reuse the last doctor mentioned
            for past in reversed(history):
                doctor = _DOCTOR_RE.search(past.content)
                if doctor:
                    break
        if re.search(r"\bspecialt|\bdepartments?\b|\bwhat (doctors|services)\b", lowered):
            return self._call("list_specializations", {})
        if _INFO_RE.search(text) and not (doctor and (when or at)):
            return self._call("clinic_info", {"question": text[:300]})
        if doctor and (when or at or re.search(r"slot|avail|book|appointment|free|time", lowered)):
            return self._call("find_doctors", {"name": doctor.group(1).strip()})
        for key, name in _SPECIALTY_WORDS.items():
            if key in lowered:
                return self._call("find_doctors", {"specialization": name})
        if re.search(r"\bdoctors?\b|\bsee\b|\bconsult", lowered):
            return self._call("find_doctors", {})
        if re.search(r"\b(hi|hello|hey|namaste|help)\b", lowered):
            return LLMResponse(
                "Hello! I can help you find a doctor, check available times and set up a booking. "
                "Try: “Which specialties do you have?” or “Show slots for Dr. Anil tomorrow”."
            )
        return LLMResponse(
            "I can help with finding a doctor, checking appointment times and booking at Bindu Clinic. "
            "What would you like to do?"
        )

    @staticmethod
    def _call(name: str, args: dict[str, Any]) -> LLMResponse:
        return LLMResponse(tool_calls=(ToolCall(id=f"mock-{name}", name=name, arguments=args),))

    # -- step 2+: turn tool results into text / chain the next tool
    def _after_tools(self, text: str, results: list[Message]) -> LLMResponse:
        last = results[-1]
        try:
            data = json.loads(last.content)
        except ValueError:
            return LLMResponse("Sorry, something went wrong looking that up.")
        if "error" in data:
            return LLMResponse(f"I couldn't do that: {data['error']}")

        if last.name == "list_specializations":
            names = ", ".join(s["name"] for s in data["specializations"])
            return LLMResponse(f"We have these specialties: {names}. Which one do you need?")

        if last.name == "clinic_info":
            passages = data.get("passages") or []
            if not passages:
                return LLMResponse("I don't have that information. Please contact the clinic reception.")
            return LLMResponse(" ".join(p["text"] for p in passages[:2]))

        if last.name == "find_doctors":
            docs = data["doctors"]
            if not docs:
                return LLMResponse("I couldn't find a matching doctor. Try a different name or specialty.")
            when, at = parse_date(text, self._now()), parse_time(text)
            wants_slots = when or at or re.search(r"slot|avail|time|book", text.lower())
            if len(docs) == 1 and wants_slots and _DOCTOR_RE.search(text):
                day = when or (self._now() + timedelta(days=1)).isoformat()
                return self._call("get_available_slots", {"doctor_id": docs[0]["id"], "date": day})
            lines = [f"{d['name']} ({d['specialization']}), ₹{d['fee']}" for d in docs]
            return LLMResponse(
                "Here are our matching doctors:\n- " + "\n- ".join(lines) + "\nAsk for a doctor's slots."
            )

        if last.name == "get_available_slots":
            slots = data["slots"]
            who, day = data["doctor_name"], data["date"]
            if not slots:
                return LLMResponse(f"{who} has no open times on {day}. Try another date?")
            wanted = parse_time(text)
            if wanted and wanted in [s[:5] for s in slots]:
                return self._call(
                    "propose_booking", {"doctor_id": data["doctor_id"], "date": day, "start_time": wanted}
                )
            shown = ", ".join(s[:5] for s in slots[:10])
            return LLMResponse(f"{who} is available on {day} at: {shown}. Tell me a time and I'll set up the booking.")

        if last.name == "propose_booking":
            s = data["summary"]
            return LLMResponse(
                f"I've prepared a booking with {s['doctor_name']} on {s['date']} at {s['start_time']}. "
                "Please enter your details in the card below and confirm."
            )
        return LLMResponse("Done.")


def build_llm(settings: Settings) -> LLMClient:
    return GrokLLM(settings) if settings.llm_mode == "live" else MockLLM()
