from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.agent.runner import run_agent_turn
from app.api.schemas import (
    ConversationDetail,
    ConversationOut,
    CreateConversationRequest,
    CreateTurnRequest,
    CreateTurnResponse,
    MessageOut,
)
from app.config import get_settings
from app.db.models import AgentRun, Conversation, ConversationEvent, Message
from app.db.session import async_session_factory, get_session
from app.events.bus import event_bus
from app.security.rate_limit import turn_limiter
from app.security.sessions import issue_session_token

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation_out(row: Conversation, *, include_token: bool = False) -> ConversationOut:
    token = issue_session_token(str(row.id)).token if include_token else None
    return ConversationOut(
        id=row.id,
        customer_id=row.customer_id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        session_token=token,
    )


def _message_out(row: Message) -> MessageOut:
    return MessageOut(
        id=row.id,
        role=row.role,
        content=row.content,
        client_turn_id=row.client_turn_id,
        run_id=row.run_id,
        meta=row.meta or {},
        created_at=row.created_at,
    )


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: CreateConversationRequest,
    session: AsyncSession = Depends(get_session),
) -> ConversationOut:
    settings = get_settings()
    conversation = Conversation(
        customer_id=body.customer_id or settings.demo_customer_id,
        title=body.title,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return _conversation_out(conversation, include_token=True)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ConversationDetail:
    row = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = sorted(row.messages, key=lambda m: m.created_at)
    return ConversationDetail(
        **_conversation_out(row).model_dump(),
        messages=[_message_out(m) for m in messages],
    )


async def _execute_turn(
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    customer_id: str,
    user_text: str,
) -> None:
    async with async_session_factory() as session:
        try:
            await run_agent_turn(
                session,
                event_bus,
                conversation_id=conversation_id,
                run_id=run_id,
                customer_id=customer_id,
                user_text=user_text,
            )
        except Exception:
            # Failure already persisted/published inside the runner.
            return


@router.post("/{conversation_id}/turns", response_model=CreateTurnResponse)
async def create_turn(
    conversation_id: uuid.UUID,
    body: CreateTurnRequest,
    session: AsyncSession = Depends(get_session),
) -> CreateTurnResponse:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not turn_limiter.allow(str(conversation_id)):
        raise HTTPException(status_code=429, detail="Turn rate limit exceeded. Try again shortly.")

    existing = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.client_turn_id == body.client_turn_id,
            Message.role == "user",
        )
    )
    if existing is not None and existing.run_id is not None:
        run = await session.get(AgentRun, existing.run_id)
        return CreateTurnResponse(
            conversation_id=conversation_id,
            run_id=existing.run_id,
            client_turn_id=body.client_turn_id,
            status=run.status if run else "completed",
        )

    run_id = uuid.uuid4()
    run = AgentRun(
        id=run_id,
        conversation_id=conversation_id,
        client_turn_id=body.client_turn_id,
        status="running",
    )
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=body.text.strip(),
        client_turn_id=body.client_turn_id,
        run_id=run_id,
        meta={},
    )
    conversation.updated_at = datetime.now(timezone.utc)
    session.add(run)
    session.add(user_message)
    await session.commit()

    # Start immediately so SSE subscribers receive tool events without waiting
    # for the HTTP response lifecycle (BackgroundTasks runs after response).
    asyncio.create_task(
        _execute_turn(
            conversation_id,
            run_id,
            conversation.customer_id,
            body.text.strip(),
        )
    )
    return CreateTurnResponse(
        conversation_id=conversation_id,
        run_id=run_id,
        client_turn_id=body.client_turn_id,
        status="running",
    )


@router.get("/{conversation_id}/events")
async def stream_events(
    conversation_id: uuid.UUID,
    request: Request,
    after: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        # Subscribe first so live events are not missed while replaying history.
        queue = await event_bus.subscribe(conversation_id)
        last_seen = after
        try:
            async with async_session_factory() as replay_session:
                rows = (
                    await replay_session.scalars(
                        select(ConversationEvent)
                        .where(
                            ConversationEvent.conversation_id == conversation_id,
                            ConversationEvent.sequence > after,
                        )
                        .order_by(ConversationEvent.sequence.asc())
                    )
                ).all()
                for row in rows:
                    last_seen = row.sequence
                    payload = {
                        "id": row.id,
                        "sequence": row.sequence,
                        "conversation_id": str(row.conversation_id),
                        "run_id": str(row.run_id) if row.run_id else None,
                        "event_type": row.event_type,
                        "payload": row.payload or {},
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                    yield {
                        "id": str(row.sequence),
                        "event": row.event_type,
                        "data": json.dumps(payload),
                    }

            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if event["sequence"] <= last_seen:
                    continue
                last_seen = event["sequence"]
                yield {
                    "id": str(event["sequence"]),
                    "event": event["event_type"],
                    "data": json.dumps(event),
                }
        finally:
            await event_bus.unsubscribe(conversation_id, queue)

    # The generator already emits a ping event every 10s. sse-starlette treats
    # ping=0 as "ping continuously", which pins the CPU, so keep a real interval.
    return EventSourceResponse(event_generator(), ping=15)
