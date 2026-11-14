"""Chatbot endpoints: ``POST /chat`` (assistant turn) and ``POST /chat/confirm`` (human-confirmed booking)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat import ChatService, ChatTurn
from app.ai.llm import LLMClient, build_llm
from app.ai.proposals import read_proposal
from app.ai.tools import ToolRegistry
from app.api.routes.booking import get_booking_service, get_clock
from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimiter, rate_limited
from app.database.session import get_session
from app.repositories.booking import BookingRepository
from app.repositories.catalog import CatalogRepository
from app.schemas.booking import AppointmentOut
from app.schemas.chat import ChatRequest, ChatResponse, ConfirmRequest, Proposal, ProposalSummary
from app.services.booking import BookCommand, BookingService

router = APIRouter(prefix="/chat", tags=["chat"])

_chat_limiter = RateLimiter(limit=20, window_seconds=60)
_confirm_limiter = RateLimiter(limit=10, window_seconds=60)


def get_llm(settings: Settings = Depends(get_settings)) -> LLMClient:
    return build_llm(settings)


def get_chat_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> ChatService:
    tools = ToolRegistry(CatalogRepository(session), BookingRepository(session), settings, clock)
    return ChatService(llm, tools)


@router.post("", response_model=ChatResponse, dependencies=[Depends(rate_limited(_chat_limiter))])
async def chat(body: ChatRequest, svc: ChatService = Depends(get_chat_service)) -> ChatResponse:
    result = await svc.reply([ChatTurn(m.role, m.content) for m in body.messages])
    proposal = None
    if result.proposal_token and result.proposal_summary:
        proposal = Proposal(token=result.proposal_token, summary=ProposalSummary(**result.proposal_summary))
    return ChatResponse(reply=result.reply, guard=result.guard.value, proposal=proposal)


@router.post(
    "/confirm", response_model=AppointmentOut, status_code=201, dependencies=[Depends(rate_limited(_confirm_limiter))]
)
async def confirm_booking(
    body: ConfirmRequest,
    settings: Settings = Depends(get_settings),
    booking: BookingService = Depends(get_booking_service),
) -> AppointmentOut:
    claims = read_proposal(settings, body.proposal_token)
    return await booking.book(
        BookCommand(
            doctor_id=claims["doctor_id"],
            day=claims["date"],
            start_time=claims["start_time"],
            patient_name=body.patient_name,
            phone=body.phone,
            email=body.email,
            reason="Booked via chat assistant",
            notification_consent=body.notification_consent,
            idempotency_key=f"chat-{claims['jti']}",  # a proposal can be confirmed at most once
        )
    )
