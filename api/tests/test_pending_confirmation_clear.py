"""Pending confirmation must clear on success, cancel, and invalidation — never stale."""

from __future__ import annotations

import uuid

import pytest

from app.agent.runner import run_agent_turn
from app.agent.ui_hints import pending_confirmation_ui, validate_confirmation_for_customer
from app.db.models import AgentRun, Conversation, Message
from app.domain.refunds import issue_mock_refund
from app.events.bus import EventBus


@pytest.mark.asyncio
async def test_pending_clears_after_successful_refund(session):
    conversation = Conversation(customer_id="cust_pro_001", title="confirm-success")
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
            id=run1, conversation_id=conversation.id, client_turn_id=f"s-{run1}", status="running"
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
    assert pending["confirmation"]["invoice_id"] == "INV-1042"

    await issue_mock_refund(
        session,
        conversation_id=conversation.id,
        customer_id="cust_pro_001",
        invoice_id="INV-1042",
    )
    await session.commit()

    pending2 = await pending_confirmation_ui(
        session, conversation_id=conversation.id, customer_id="cust_pro_001"
    )
    assert pending2 == {}


def test_validate_confirmation_rejects_wrong_customer_scope():
    conf = {
        "kind": "refund",
        "invoice_id": "INV-1042",
        "amount_cents": 2900,
        "currency": "USD",
    }
    assert validate_confirmation_for_customer(conf, customer_id="cust_pro_001") is not None
    assert validate_confirmation_for_customer(conf, customer_id="cust_basic_001") is None


def test_validate_confirmation_rejects_amount_mismatch():
    conf = {
        "kind": "refund",
        "invoice_id": "INV-1042",
        "amount_cents": 9999,
        "currency": "USD",
    }
    assert validate_confirmation_for_customer(conf, customer_id="cust_pro_001") is None
