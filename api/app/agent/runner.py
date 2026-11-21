from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_agent_graph, extract_final_text
from app.agent.tools import ToolContext, build_tools
from app.config import get_settings
from app.db.models import AgentRun, Message
from app.events.bus import EventBus
from app.observability.metrics import estimate_chat_cost, record_turn_metrics


def _user_facing_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "rate" in text:
        return (
            "The model provider is rate-limiting requests. Please wait a moment and try again. "
            "I can also open a human-review ticket if this keeps happening."
        )
    if "timeout" in text:
        return "The model timed out. Please retry your question."
    return f"Something went wrong while processing your request: {exc}"


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
            .limit(40)
        )
    ).all()

    lc_messages = []
    for row in history_rows:
        if row.role == "user":
            lc_messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            lc_messages.append(AIMessage(content=row.content))

    if not lc_messages or lc_messages[-1].content != user_text:
        lc_messages.append(HumanMessage(content=user_text))

    await event_bus.publish(
        session,
        conversation_id=conversation_id,
        run_id=run_id,
        event_type="run.started",
        payload={"customer_id": customer_id, "provider": settings.llm_provider, "model": settings.llm_model},
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
            payload={"message_id": str(assistant_msg.id), **cost},
        )
        await session.commit()
        return final_text
    except Exception as exc:  # noqa: BLE001
        friendly = _user_facing_error(exc)
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=friendly,
            run_id=run_id,
            meta={"error": True, "provider": settings.llm_provider},
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
            payload={"text": friendly},
        )
        await event_bus.publish(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="run.failed",
            payload={"error": str(exc)},
        )
        await session.commit()
        return friendly
