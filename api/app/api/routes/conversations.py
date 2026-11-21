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
    CancelConfirmationResponse,
    ConversationDetail,
    ConversationOut,
    CreateConversationRequest,
    CreateTurnRequest,
    CreateTurnResponse,
    MessageOut,
    RetryFailedRunRequest,
    RetryFailedRunResponse,
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
    *,
    source: str = "chat",
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
                source=source,
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


@router.post(
    "/{conversation_id}/runs/{failed_run_id}/retry",
    response_model=RetryFailedRunResponse,
)
async def retry_failed_run(
    conversation_id: uuid.UUID,
    failed_run_id: uuid.UUID,
    body: RetryFailedRunRequest,
    session: AsyncSession = Depends(get_session),
) -> RetryFailedRunResponse:
    """Re-run a failed agent turn without inserting another user message.

    Idempotent on ``client_retry_id`` (duplicate clicks return the same retry run).
    """
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not turn_limiter.allow(str(conversation_id)):
        raise HTTPException(status_code=429, detail="Turn rate limit exceeded. Try again shortly.")

    failed_run = await session.get(AgentRun, failed_run_id)
    if failed_run is None or failed_run.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Failed run not found")
    if failed_run.status != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Run is {failed_run.status}; only failed runs can be retried",
        )

    user_message = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.run_id == failed_run_id,
            Message.role == "user",
        )
    )
    if user_message is None:
        raise HTTPException(status_code=404, detail="Original user message not found for run")

    # Infer source from the failed assistant error bubble when present.
    failed_assistant = await session.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.run_id == failed_run_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc())
    )
    source = "chat"
    if failed_assistant and isinstance(failed_assistant.meta, dict):
        source = str(failed_assistant.meta.get("source") or "chat")
    if source not in {"chat", "voice"}:
        source = "chat"

    retry_client_turn_id = f"retry:{failed_run_id}:{body.client_retry_id}"
    existing_retry = await session.scalar(
        select(AgentRun).where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.client_turn_id == retry_client_turn_id,
        )
    )
    if existing_retry is not None:
        return RetryFailedRunResponse(
            conversation_id=conversation_id,
            run_id=existing_retry.id,
            failed_run_id=failed_run_id,
            client_retry_id=body.client_retry_id,
            status=existing_retry.status,
            source=source,
            reused=True,
        )

    # Supersede the error assistant bubble so history/UI don't keep a dead retry prompt.
    if failed_assistant is not None:
        meta = dict(failed_assistant.meta or {})
        meta["superseded"] = True
        failed_assistant.meta = meta

    new_run_id = uuid.uuid4()
    run = AgentRun(
        id=new_run_id,
        conversation_id=conversation_id,
        client_turn_id=retry_client_turn_id,
        status="running",
    )
    # Link retry to the same user utterance without duplicating the message row
    # and without reassigning user_message.run_id (keeps failed_run_id lookup stable
    # for duplicate-click retries).
    user_meta = dict(user_message.meta or {})
    prior = list(user_meta.get("retry_run_ids") or [])
    prior.append(str(new_run_id))
    user_meta["retry_run_ids"] = prior[-8:]
    user_meta["last_retry_of"] = str(failed_run_id)
    user_message.meta = user_meta

    conversation.updated_at = datetime.now(timezone.utc)
    session.add(run)
    await session.commit()

    asyncio.create_task(
        _execute_turn(
            conversation_id,
            new_run_id,
            conversation.customer_id,
            user_message.content,
            source=source,
        )
    )
    return RetryFailedRunResponse(
        conversation_id=conversation_id,
        run_id=new_run_id,
        failed_run_id=failed_run_id,
        client_retry_id=body.client_retry_id,
        status="running",
        source=source,
        reused=False,
    )


@router.post(
    "/{conversation_id}/confirmation/cancel",
    response_model=CancelConfirmationResponse,
)
async def cancel_pending_confirmation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CancelConfirmationResponse:
    """Explicitly clear pending refund confirmation (never restore as stale)."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await event_bus.publish(
        session,
        conversation_id=conversation_id,
        run_id=None,
        event_type="confirmation.cancelled",
        payload={"customer_id": conversation.customer_id, "reason": "user_cancelled"},
    )
    await session.commit()
    return CancelConfirmationResponse(conversation_id=conversation_id, cancelled=True)


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
