"""Chatbot guardrails: deterministic checks that run *before* and *after* the model.

Order of precedence for user input: emergency > prompt-injection > medical advice.
Emergency and medical requests never reach the LLM, so they cannot be talked around.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

MAX_MESSAGE_CHARS = 500
MAX_HISTORY_MESSAGES = 12
MAX_TOTAL_CHARS = 4000
MAX_REPLY_CHARS = 1200

# Planted in the system prompt; if it ever appears in a reply the prompt is leaking.
CANARY = "ZX-CANARY-7731"

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


class Verdict(StrEnum):
    OK = "none"
    EMERGENCY = "emergency"
    INJECTION = "injection"
    MEDICAL = "medical"


@dataclass(frozen=True)
class GuardResult:
    verdict: Verdict
    reply: str | None = None  # canned response when the request must not reach the LLM


def normalize(text: str) -> str:
    """NFKC-fold, strip zero-width characters, lowercase and collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).lower()
    return re.sub(r"\s+", " ", text).strip()


_EMERGENCY = re.compile(
    r"chest pain|heart attack|can'?t breathe|cannot breathe|difficulty breathing|short(ness)? of breath|"
    r"stroke|unconscious|not breathing|severe bleeding|bleeding (heavily|a lot)|seizure|overdose|poison|"
    r"suicid|kill myself|end my life|want to die|self[- ]harm|anaphyla|choking|collapsed"
)
_INJECTION = re.compile(
    r"(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|all|your|the|these)\b.{0,30}"
    r"\b(instruction|rule|prompt|guideline|polic|restriction)|"
    r"(reveal|show|print|repeat|display|leak|tell me)\b.{0,30}\b(system|initial|hidden|your)\b.{0,15}"
    r"\b(prompt|instruction|rule)|"
    r"system prompt|developer mode|jailbreak|\bdan mode\b|you are now\b|from now on you|act as (an? )?(?!patient)|"
    r"pretend (to be|you)|new instructions?:|</?(system|assistant)>|\[/?inst\]|"
    r"(call|use|run|execute) (the )?(book|confirm|cancel)[a-z_ ]*(tool|function)"
)
_MEDICAL = re.compile(
    r"what (medicine|medication|drug|tablet|pill)s?\b|which (medicine|medication|drug|tablet|pill)s?\b|"
    r"\bdosage\b|\bdose\b|how (much|many) (mg|tablets?|pills?)|\bprescrib|\bdiagnos|"
    r"is (it|this) (serious|cancer|dangerous|contagious)|should i (take|stop|skip)|"
    r"side effects? of|can i take .* (with|and) |treat my|cure (for|my)|home remed|what('s| is) wrong with me|"
    r"interpret (my )?(report|result|scan|test)|lab results?"
)


def emergency_reply(number: str = "112") -> str:
    return (
        f"This sounds like it could be an emergency. Please call {number} or go to the nearest emergency "
        "department right now. I can't help with emergencies through chat, and online booking is not suitable."
    )


MEDICAL_REPLY = (
    "I can't give medical advice, diagnoses or medication guidance. A doctor can help with that. "
    "I'd be happy to help you find the right doctor and book an appointment. "
    "Tell me which specialty you need, or ask me to list our specialties."
)

INJECTION_REPLY = (
    "I can only help with finding doctors, checking appointment times and booking at Bindu Clinic. "
    "What would you like to do?"
)


def check_input(text: str, emergency_number: str = "112") -> GuardResult:
    folded = normalize(text)
    if _EMERGENCY.search(folded):
        return GuardResult(Verdict.EMERGENCY, emergency_reply(emergency_number))
    if _INJECTION.search(folded):
        return GuardResult(Verdict.INJECTION, INJECTION_REPLY)
    if _MEDICAL.search(folded):
        return GuardResult(Verdict.MEDICAL, MEDICAL_REPLY)
    return GuardResult(Verdict.OK)


_URL = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_DOSAGE = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|iu)\b", re.IGNORECASE)

SAFE_FALLBACK = (
    "Sorry, I couldn't put together a helpful answer. I can list our specialties, find a doctor or check "
    "available appointment times for you."
)


def check_output(reply: str) -> str:
    """Return a safe reply: no prompt leakage, external links or dosage-like content."""
    if not reply or not reply.strip():
        return SAFE_FALLBACK
    if CANARY in reply or _DOSAGE.search(reply):
        return SAFE_FALLBACK
    reply = _URL.sub("[link removed]", reply).strip()
    return reply[:MAX_REPLY_CHARS]
