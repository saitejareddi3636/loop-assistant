from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationEvent, Message, MockReceipt, EscalationTicket


async def load_tool_events(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.sequence.asc())
        )
    ).all()
    return [
        {
            "sequence": r.sequence,
            "event_type": r.event_type,
            "run_id": str(r.run_id) if r.run_id else None,
            "payload": r.payload or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def load_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).all()
    return [
        {
            "role": r.role,
            "content": r.content,
            "run_id": str(r.run_id) if r.run_id else None,
            "meta": r.meta or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def conversation_snapshot(session: AsyncSession, conversation_id: uuid.UUID) -> dict[str, Any]:
    receipts = (
        await session.scalars(select(MockReceipt).where(MockReceipt.conversation_id == conversation_id))
    ).all()
    tickets = (
        await session.scalars(
            select(EscalationTicket).where(EscalationTicket.conversation_id == conversation_id)
        )
    ).all()
    return {
        "messages": await load_messages(session, conversation_id),
        "events": await load_tool_events(session, conversation_id),
        "receipts": [
            {
                "id": str(r.id),
                "invoice_id": r.invoice_id,
                "customer_id": r.customer_id,
                "amount_cents": r.amount_cents,
                "status": r.status,
            }
            for r in receipts
        ],
        "tickets": [
            {"id": t.id, "reason": t.reason, "status": t.status, "references": t.references}
            for t in tickets
        ],
    }
