from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.runner import run_agent_turn
from app.agent.tools import ToolContext, build_tools
from app.db.models import Conversation, EscalationTicket, Message
from app.events.bus import EventBus


@pytest.mark.asyncio
async def test_mock_agent_billing_flow_persists_assistant_message(session):
    conversation = Conversation(customer_id="cust_pro_001", title="test")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    run_id = uuid.uuid4()
    user = Message(
        conversation_id=conversation.id,
        role="user",
        content="I was charged twice on INV-1042. Can you help?",
        client_turn_id=str(uuid.uuid4()),
        run_id=run_id,
    )
    session.add(user)
    await session.commit()

    text = await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run_id,
        customer_id="cust_pro_001",
        user_text=user.content,
    )
    assert "INV-1042" in text
    assert "PRO-BILL" in text or "refund" in text.lower()

    rows = (
        await session.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
            )
        )
    ).all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_mock_agent_escalates_out_of_scope(session):
    conversation = Conversation(customer_id="cust_pro_001", title="escalate")
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)

    run_id = uuid.uuid4()
    user_text = "Can you help with my home insurance coverage lawsuit?"
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=user_text,
            client_turn_id=str(uuid.uuid4()),
            run_id=run_id,
        )
    )
    await session.commit()

    text = await run_agent_turn(
        session,
        EventBus(),
        conversation_id=conversation.id,
        run_id=run_id,
        customer_id="cust_pro_001",
        user_text=user_text,
    )
    assert "ticket" in text.lower()
    tickets = (await session.scalars(select(EscalationTicket))).all()
    assert any(t.conversation_id == conversation.id for t in tickets)


@pytest.mark.asyncio
async def test_tool_scope_mismatch_blocks_cross_customer_access(session):
    conversation = Conversation(customer_id="cust_pro_001", title="scope")
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
    result = await tools["get_invoice"].ainvoke(
        {"invoice_id": "INV-2001", "customer_id": "cust_basic_001"}
    )
    assert result["ok"] is False
    assert result["error"] == "customer_scope_mismatch"
