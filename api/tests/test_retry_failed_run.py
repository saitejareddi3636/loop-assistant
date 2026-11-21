"""Safe retry of failed runs: no duplicate user messages, idempotent clicks, source isolation."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.agent.runner import run_agent_turn
from app.db.models import AgentRun, Conversation, Message
from app.events.bus import EventBus


async def _fail_confirm_turn(session, conversation, monkeypatch, *, source: str = "chat"):
    from app.agent import graph as graph_mod

    class RateLimitError(Exception):
        def __init__(self):
            super().__init__("Error code: 429 - Rate limit reached for model")
            self.status_code = 429
            self.response = type("R", (), {"headers": {"retry-after": "1"}})()

    async def boom(_model, _messages):
        raise RateLimitError()

    monkeypatch.setattr(graph_mod, "ainvoke_with_retries", boom)

    run_id = uuid.uuid4()
    text = "Yes, confirm the $29 refund on INV-1042"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=text,
            client_turn_id=str(uuid.uuid4()),
            run_id=run_id,
            meta={"source": source},
        )
    )
    session.add(
        AgentRun(
            id=run_id,
            conversation_id=conversation.id,
            client_turn_id=f"turn-{run_id}",
            status="running",
        )
    )
    await session.commit()
    await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run_id,
        customer_id="cust_pro_001",
        user_text=text,
        source=source,
    )
    return run_id, text


@pytest.mark.asyncio
async def test_retry_endpoint_does_not_duplicate_user_message(client, session, monkeypatch):
    # Seed confirmation then failed confirm via HTTP-ish flow using DB + retry API
    conversation = Conversation(customer_id="cust_pro_001", title="retry-safe")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    run1 = uuid.uuid4()
    ask = "I was charged twice on INV-1042. Can you help?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=ask,
            client_turn_id=str(uuid.uuid4()),
            run_id=run1,
        )
    )
    session.add(
        AgentRun(
            id=run1,
            conversation_id=conversation.id,
            client_turn_id=f"ask-{run1}",
            status="running",
        )
    )
    await session.commit()
    await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run1,
        customer_id="cust_pro_001",
        user_text=ask,
    )

    failed_run_id, text = await _fail_confirm_turn(session, conversation, monkeypatch)

    before = await session.scalar(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
            Message.content == text,
        )
    )

    retry_id = "retry-click-aaaa-bbbb"
    first = await client.post(
        f"/api/conversations/{conversation.id}/runs/{failed_run_id}/retry",
        json={"client_retry_id": retry_id},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["reused"] is False
    assert body["failed_run_id"] == str(failed_run_id)
    assert body["source"] == "chat"

    second = await client.post(
        f"/api/conversations/{conversation.id}/runs/{failed_run_id}/retry",
        json={"client_retry_id": retry_id},
    )
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == body["run_id"]

    await session.refresh(
        (
            await session.scalars(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.role == "user",
                    Message.content == text,
                )
            )
        ).first()
    )
    after = await session.scalar(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
            Message.content == text,
        )
    )
    assert after == before == 1


@pytest.mark.asyncio
async def test_voice_failed_run_retries_as_voice_source(client, session, monkeypatch):
    conversation = Conversation(customer_id="cust_pro_001", title="voice-retry")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    # Establish confirmation first
    run1 = uuid.uuid4()
    ask = "I was charged twice on INV-1042. Can you help?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=ask,
            client_turn_id=str(uuid.uuid4()),
            run_id=run1,
        )
    )
    session.add(
        AgentRun(
            id=run1, conversation_id=conversation.id, client_turn_id=f"a-{run1}", status="running"
        )
    )
    await session.commit()
    await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run1,
        customer_id="cust_pro_001",
        user_text=ask,
    )

    failed_run_id, _ = await _fail_confirm_turn(
        session, conversation, monkeypatch, source="voice"
    )
    resp = await client.post(
        f"/api/conversations/{conversation.id}/runs/{failed_run_id}/retry",
        json={"client_retry_id": "voice-retry-1111"},
    )
    assert resp.status_code == 200
    assert resp.json()["source"] == "voice"


@pytest.mark.asyncio
async def test_cancel_confirmation_clears_pending(client, session):
    from app.agent.ui_hints import pending_confirmation_ui
    from app.events.bus import EventBus

    conversation = Conversation(customer_id="cust_pro_001", title="cancel-confirm")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    run1 = uuid.uuid4()
    ask = "I was charged twice on INV-1042. Can you help?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=ask,
            client_turn_id=str(uuid.uuid4()),
            run_id=run1,
        )
    )
    session.add(
        AgentRun(
            id=run1, conversation_id=conversation.id, client_turn_id=f"c-{run1}", status="running"
        )
    )
    await session.commit()
    await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run1,
        customer_id="cust_pro_001",
        user_text=ask,
    )
    pending = await pending_confirmation_ui(
        session, conversation_id=conversation.id, customer_id="cust_pro_001"
    )
    assert "confirmation" in pending

    conv_id = conversation.id
    resp = await client.post(f"/api/conversations/{conv_id}/confirmation/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True

    session.expire_all()
    pending2 = await pending_confirmation_ui(
        session, conversation_id=conv_id, customer_id="cust_pro_001"
    )
    assert pending2 == {}
