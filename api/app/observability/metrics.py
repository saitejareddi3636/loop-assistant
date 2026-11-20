from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationEvent
from app.events.bus import event_bus

# Rough public list prices (USD / 1M tokens). Update as needed; used for estimates only.
_MODEL_RATES: dict[str, tuple[float, float]] = {
    # (input_per_mtok, output_per_mtok)
    "openai/gpt-oss-120b": (0.15, 0.60),
    "gpt-4o-mini": (0.15, 0.60),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mock-support": (0.0, 0.0),
}


def estimate_chat_cost(*, model: str, prompt_chars: int, completion_chars: int) -> dict[str, Any]:
    # Heuristic: ~4 chars/token.
    prompt_tokens = max(1, prompt_chars // 4)
    completion_tokens = max(1, completion_chars // 4)
    in_rate, out_rate = _MODEL_RATES.get(model, (0.20, 0.80))
    cost = (prompt_tokens / 1_000_000) * in_rate + (completion_tokens / 1_000_000) * out_rate
    return {
        "model": model,
        "prompt_tokens_est": prompt_tokens,
        "completion_tokens_est": completion_tokens,
        "total_tokens_est": prompt_tokens + completion_tokens,
        "estimated_cost_usd": round(cost, 8),
    }


async def record_turn_metrics(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID | None,
    metrics: dict[str, Any],
) -> ConversationEvent | None:
    event = await event_bus.publish(
        session,
        conversation_id=conversation_id,
        run_id=run_id,
        event_type="obs.metrics",
        payload=metrics,
    )
    return event  # type: ignore[return-value]
