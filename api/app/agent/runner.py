from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_agent_graph, extract_final_text
from app.agent.llm import (
    RateLimitBudgetExceeded,
    extract_retry_after_seconds,
    is_rate_limit_error,
)
from app.agent.tools import ToolContext, build_tools
from app.config import get_settings
from app.db.models import AgentRun, Message
from app.events.bus import EventBus
from app.observability.metrics import estimate_chat_cost, record_turn_metrics

# Keep recent turns only to reduce TPM on Groq free/on_demand tiers.
_HISTORY_LIMIT = 12


def _user_facing_error(exc: Exception) -> str:
    if isinstance(exc, RateLimitBudgetExceeded):
        wait = max(1, int(exc.retry_after_seconds))
        return (
            f"The model provider asked us to wait {wait} seconds before trying again "
            f"(longer than our automatic retry window). Please wait about {wait}s, then tap Retry — "
            "your conversation and any still-valid refund confirmation stay here."
        )
    if is_rate_limit_error(exc):
        retry_after = extract_retry_after_seconds(exc)
        wait = f" Wait about {int(retry_after)} seconds," if retry_after else " Wait a moment,"
        return (
            f"The model provider is rate-limiting requests.{wait} then tap Retry — "
            "your conversation and any still-valid refund confirmation are still here."
        )
    text = str(exc).lower()
    if "timeout" in text:
        return "The model timed out. Please retry — the conversation is unchanged."
    return f"Something went wrong while processing your request: {exc}"


def _is_recoverable(exc: Exception) -> bool:
    if isinstance(exc, RateLimitBudgetExceeded):
        return True  # user can retry after waiting; we do not auto-loop
    if is_rate_limit_error(exc):
        return True
    text = str(exc).lower()
    return "timeout" in text or "503" in text or "502" in text


def _trim_history(rows: list[Message]) -> list:
    """Drop older turns and prior provider-error assistants to save tokens."""
    usable = list(rows)
    if len(usable) > _HISTORY_LIMIT:
        usable = usable[-_HISTORY_LIMIT:]
    lc_messages = []
    for row in usable:
        meta = row.meta or {}
        if row.role == "assistant" and meta.get("error") and meta.get("retryable"):
            continue
        if meta.get("superseded"):
            continue
        if row.role == "user":
            lc_messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            content = row.content if len(row.content) <= 800 else row.content[:800] + "…"
            lc_messages.append(AIMessage(content=content))
    return lc_messages


async def run_agent_turn(
    session: AsyncSession,
    event_bus: EventBus,
    *,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
    customer_id: str,
    user_text: str,
    source: str = "chat",
    extra_metrics: dict | None = None,
) -> str:
    settings = get_settings()
    ctx = ToolContext(
        session=session,
        event_bus=event_bus,
        conversation_id=conversation_id,
        run_id=run_id,
        customer_id=customer_id,
    )
    tools = build_tools(ctx)
    graph = build_agent_graph(tools, voice=source == "voice")

    history_rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).all()

    lc_messages = _trim_history(list(history_rows))
    if not lc_messages or lc_messages[-1].content != user_text:
        lc_messages.append(HumanMessage(content=user_text))

    await event_bus.publish(
        session,
        conversation_id=conversation_id,
        run_id=run_id,
        event_type="run.started",
        payload={
            "customer_id": customer_id,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "source": source,
        },
    )
    await session.commit()

    try:
        result = await asyncio.wait_for(
            graph.ainvoke({"messages": lc_messages, "cycle": 0}),
            timeout=settings.agent_turn_timeout_seconds,
        )
        final_text = extract_final_text(result["messages"])

        from app.agent.ui_hints import build_assistant_ui

        ui = await build_assistant_ui(
            session, conversation_id=conversation_id, run_id=run_id
        )

        await event_bus.publish(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="assistant.delta",
            payload={"text": final_text, "ui": ui},
        )
        if ui:
            await event_bus.publish(
                session,
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="assistant.ui",
                payload=ui,
            )

        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_text,
            run_id=run_id,
            meta={
                "model": settings.llm_model,
                "provider": settings.llm_provider,
                "source": source,
                "ui": ui,
            },
        )
        session.add(assistant_msg)

        run = await session.get(AgentRun, run_id)
        if run is not None:
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)

        cost = estimate_chat_cost(
            model=settings.llm_model,
            prompt_chars=len(user_text),
            completion_chars=len(final_text),
        )
        await record_turn_metrics(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            metrics={
                "source": source,
                "provider": settings.llm_provider,
                **cost,
                **(extra_metrics or {}),
            },
        )
        await event_bus.publish(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="run.completed",
            payload={"message_id": str(assistant_msg.id), "source": source, **cost},
        )
        await session.commit()
        return final_text
    except Exception as exc:  # noqa: BLE001
        from app.agent.ui_hints import pending_confirmation_ui

        friendly = _user_facing_error(exc)
        recoverable = _is_recoverable(exc)
        if isinstance(exc, RateLimitBudgetExceeded):
            retry_after = exc.retry_after_seconds
            wait_required = True
        else:
            retry_after = extract_retry_after_seconds(exc)
            wait_required = False
        ui = await pending_confirmation_ui(
            session, conversation_id=conversation_id, customer_id=customer_id
        )

        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=friendly,
            run_id=run_id,
            meta={
                "error": True,
                "retryable": recoverable,
                "rate_limited": is_rate_limit_error(exc)
                or isinstance(exc, RateLimitBudgetExceeded),
                "retry_after_seconds": retry_after,
                "wait_required": wait_required,
                "provider": settings.llm_provider,
                "source": source,
                "ui": ui,
            },
        )
        session.add(assistant_msg)

        run = await session.get(AgentRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)

        await event_bus.publish(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="assistant.delta",
            payload={"text": friendly, "ui": ui, "retryable": recoverable, "source": source},
        )
        if ui:
            await event_bus.publish(
                session,
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="assistant.ui",
                payload=ui,
            )
        await event_bus.publish(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="run.failed",
            payload={
                "error": str(exc),
                "retryable": recoverable,
                "rate_limited": is_rate_limit_error(exc)
                or isinstance(exc, RateLimitBudgetExceeded),
                "retry_after_seconds": retry_after,
                "wait_required": wait_required,
                "user_message": friendly,
                "source": source,
                "ui": ui,
            },
        )
        await session.commit()
        return friendly
