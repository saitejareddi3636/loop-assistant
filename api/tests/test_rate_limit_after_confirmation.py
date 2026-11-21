"""Regression: Groq 429 after refund confirmation request must preserve UI and not duplicate side effects."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.runner import run_agent_turn
from app.db.models import Conversation, ConversationEvent, EscalationTicket, Message, MockReceipt
from app.domain.refunds import issue_mock_refund
from app.events.bus import EventBus


@pytest.mark.asyncio
async def test_429_after_confirmation_preserves_pending_ui(session, monkeypatch):
    """After confirmation_required, a rate-limited confirm turn keeps the confirmation card."""
    conversation = Conversation(customer_id="cust_pro_001", title="429-confirm")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    # Turn 1: establish pending confirmation via mock agent
    run1 = uuid.uuid4()
    text1 = "I was charged twice on INV-1042. Can you help?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=text1,
            client_turn_id=str(uuid.uuid4()),
            run_id=run1,
        )
    )
    await session.commit()
    await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run1,
        customer_id="cust_pro_001",
        user_text=text1,
    )

    # Turn 2: user confirms, but LLM hits 429
    from app.agent import graph as graph_mod

    class RateLimitError(Exception):
        def __init__(self):
            super().__init__("Error code: 429 - Rate limit reached for model")
            self.status_code = 429
            self.response = type("R", (), {"headers": {"retry-after": "2"}})()

    async def boom_ainvoke(_model, _messages):
        raise RateLimitError()

    monkeypatch.setattr(graph_mod, "ainvoke_with_retries", boom_ainvoke)

    run2 = uuid.uuid4()
    text2 = "Yes, confirm the $29 refund on INV-1042"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=text2,
            client_turn_id=str(uuid.uuid4()),
            run_id=run2,
        )
    )
    await session.commit()

    reply = await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run2,
        customer_id="cust_pro_001",
        user_text=text2,
    )
    assert "rate-limiting" in reply.lower() or "retry" in reply.lower()

    assistant = (
        await session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
                Message.run_id == run2,
            )
            .order_by(Message.created_at.desc())
        )
    ).first()
    assert assistant is not None
    meta = assistant.meta or {}
    assert meta.get("retryable") is True
    assert meta.get("rate_limited") is True
    conf = (meta.get("ui") or {}).get("confirmation")
    assert conf is not None
    assert conf["invoice_id"] == "INV-1042"
    assert conf["amount_cents"] == 2900

    # No refund receipt created despite the failed confirm turn
    receipts = (
        await session.scalars(
            select(MockReceipt).where(MockReceipt.conversation_id == conversation.id)
        )
    ).all()
    assert receipts == []

    failed_events = (
        await session.scalars(
            select(ConversationEvent).where(
                ConversationEvent.conversation_id == conversation.id,
                ConversationEvent.event_type == "run.failed",
            )
        )
    ).all()
    assert failed_events
    payload = failed_events[-1].payload or {}
    assert payload.get("retryable") is True
    assert (payload.get("ui") or {}).get("confirmation", {}).get("invoice_id") == "INV-1042"


@pytest.mark.asyncio
async def test_refund_retry_does_not_duplicate_receipt(session):
    conversation = Conversation(customer_id="cust_pro_001", title="refund-idem")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    first = await issue_mock_refund(
        session,
        conversation_id=conversation.id,
        customer_id="cust_pro_001",
        invoice_id="INV-1042",
    )
    second = await issue_mock_refund(
        session,
        conversation_id=conversation.id,
        customer_id="cust_pro_001",
        invoice_id="INV-1042",
    )
    await session.commit()
    assert first["ok"] and second["ok"]
    assert second.get("reused") is True
    assert first["receipt"]["id"] == second["receipt"]["id"]
    rows = (
        await session.scalars(
            select(MockReceipt).where(
                MockReceipt.customer_id == "cust_pro_001",
                MockReceipt.invoice_id == "INV-1042",
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_ticket_retry_does_not_duplicate(session):
    from app.agent.tools import ToolContext, build_tools
    from app.events.bus import EventBus

    conversation = Conversation(customer_id="cust_pro_001", title="ticket-idem")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    ctx = ToolContext(
        session=session,
        event_bus=EventBus(),
        conversation_id=conversation.id,
        run_id=uuid.uuid4(),
        customer_id="cust_pro_001",
    )
    tools = {t.name: t for t in build_tools(ctx)}
    reason = "Basic tier duplicate refund requires human review"
    first = await tools["create_ticket"].ainvoke(
        {"reason": reason, "customer_id": "cust_pro_001", "references": []}
    )
    second = await tools["create_ticket"].ainvoke(
        {"reason": reason, "customer_id": "cust_pro_001", "references": []}
    )
    assert first["ok"] and second["ok"]
    assert second.get("reused") is True
    assert first["ticket"]["id"] == second["ticket"]["id"]
    rows = (
        await session.scalars(
            select(EscalationTicket).where(EscalationTicket.conversation_id == conversation.id)
        )
    ).all()
    assert len(rows) == 1
