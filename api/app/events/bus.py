from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationEvent


class EventBus:
    """Persists conversation events and fans them out to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, conversation_id: uuid.UUID) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers[conversation_id].add(queue)
        return queue

    async def unsubscribe(self, conversation_id: uuid.UUID, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(conversation_id)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(conversation_id, None)

    async def publish(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        run_id: uuid.UUID | None,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        next_seq = await session.scalar(
            select(func.coalesce(func.max(ConversationEvent.sequence), 0)).where(
                ConversationEvent.conversation_id == conversation_id
            )
        )
        sequence = int(next_seq or 0) + 1
        row = ConversationEvent(
            conversation_id=conversation_id,
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload or {},
        )
        session.add(row)
        await session.flush()

        event = {
            "id": row.id,
            "sequence": sequence,
            "conversation_id": str(conversation_id),
            "run_id": str(run_id) if run_id else None,
            "event_type": event_type,
            "payload": payload or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        await self._fanout(conversation_id, event)
        return event

    async def _fanout(self, conversation_id: uuid.UUID, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(conversation_id, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest-style pressure: skip if a slow client falls behind.
                continue


event_bus = EventBus()
