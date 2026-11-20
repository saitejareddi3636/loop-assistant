from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.runner import run_agent_turn
from app.agent.ui_hints import build_assistant_ui
from app.db.models import Conversation, ConversationEvent, Message
from app.events.bus import EventBus


@pytest.mark.asyncio
async def test_policy_question_has_no_confirmation_ui(session):
    conversation = Conversation(customer_id="cust_pro_001", title="policy-ui")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    run_id = uuid.uuid4()
    text = "What is the Pro refund policy for duplicate charges?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=text,
            client_turn_id=str(uuid.uuid4()),
            run_id=run_id,
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
    )
    assistant = (
        await session.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
            )
        )
    ).first()
    assert assistant is not None
    ui = (assistant.meta or {}).get("ui") or {}
    assert "confirmation" not in ui


@pytest.mark.asyncio
async def test_refund_ask_sets_structured_confirmation(session):
    conversation = Conversation(customer_id="cust_pro_001", title="refund-ui")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    run_id = uuid.uuid4()
    text = "I was charged twice on INV-1042. Can you help?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=text,
            client_turn_id=str(uuid.uuid4()),
            run_id=run_id,
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
    )
    assistant = (
        await session.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
            )
        )
    ).first()
    assert assistant is not None
    ui = (assistant.meta or {}).get("ui") or {}
    conf = ui.get("confirmation")
    assert conf is not None
    assert conf["kind"] == "refund"
    assert conf["invoice_id"] == "INV-1042"
    assert conf["amount_cents"] == 2900
    assert conf["requires_explicit_confirm"] is True

    # Also published as assistant.ui event
    events = (
        await session.scalars(
            select(ConversationEvent).where(
                ConversationEvent.conversation_id == conversation.id,
                ConversationEvent.event_type == "assistant.ui",
            )
        )
    ).all()
    assert events
