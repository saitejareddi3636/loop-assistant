from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentRun,
    Conversation,
    ConversationEvent,
    EscalationTicket,
    Message,
    MockReceipt,
)


async def reset_mutable_eval_state(session: AsyncSession) -> None:
    """Clear conversation/refund artifacts between scenarios on the isolated evals DB."""
    await session.execute(delete(MockReceipt))
    await session.execute(delete(EscalationTicket))
    await session.execute(delete(ConversationEvent))
    await session.execute(delete(Message))
    await session.execute(delete(AgentRun))
    await session.execute(delete(Conversation))
    await session.commit()
