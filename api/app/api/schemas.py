from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    customer_id: str | None = None
    title: str = "Support chat"


class ConversationOut(BaseModel):
    id: UUID
    customer_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    session_token: str | None = None


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    client_turn_id: str | None = None
    run_id: UUID | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class CreateTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_turn_id: str = Field(min_length=8, max_length=128)


class CreateTurnResponse(BaseModel):
    conversation_id: UUID
    run_id: UUID
    client_turn_id: str
    status: str


class RetryFailedRunRequest(BaseModel):
    """Idempotent retry of a failed run without duplicating the user message."""

    client_retry_id: str = Field(min_length=8, max_length=128)


class RetryFailedRunResponse(BaseModel):
    conversation_id: UUID
    run_id: UUID
    failed_run_id: UUID
    client_retry_id: str
    status: str
    source: str
    reused: bool = False


class CancelConfirmationResponse(BaseModel):
    conversation_id: UUID
    cancelled: bool


class HealthOut(BaseModel):
    status: str
    database: str
    llm_configured: bool
    model: str


class TranscribeResponse(BaseModel):
    """Dictation-only STT result — never creates messages or runs the agent."""

    text: str
    stt_ms: float
    stt_provider: str
    sample_rate: int
    duration_ms: float
