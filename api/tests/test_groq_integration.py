from __future__ import annotations

import os
import uuid

import pytest
from langchain_core.messages import HumanMessage

from app.agent.llm import get_chat_model
from app.config import get_settings


def _groq_configured() -> bool:
    return bool(os.getenv("GROQ_API_KEY") or get_settings().groq_api_key)


@pytest.mark.asyncio
@pytest.mark.skipif(not _groq_configured(), reason="GROQ_API_KEY not configured")
async def test_groq_model_responds():
    # Temporarily force groq for this test.
    os.environ["LLM_PROVIDER"] = "groq"
    os.environ["LLM_MODEL"] = "openai/gpt-oss-120b"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai/v1"
    get_settings.cache_clear()

    model = get_chat_model()
    resp = await model.ainvoke([HumanMessage(content="Reply with exactly: PONG")])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    assert "PONG" in text.upper()

    # Restore mock defaults for remaining tests in this process.
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MODEL"] = "mock-support"
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.skipif(not _groq_configured(), reason="GROQ_API_KEY not configured")
async def test_groq_agent_tool_loop(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    get_settings.cache_clear()

    # Recreate app settings by hitting health through existing client may still use old
    # process settings; call runner directly for a reliable assertion.
    from app.agent.runner import run_agent_turn
    from app.db.models import Conversation, Message
    from app.db.session import async_session_factory
    from app.events.bus import EventBus

    async with async_session_factory() as session:
        conversation = Conversation(customer_id="cust_pro_001", title="groq")
        session.add(conversation)
        await session.commit()
        await session.refresh(conversation)
        run_id = uuid.uuid4()
        user_text = "I was charged twice on INV-1042. Can you help with a refund?"
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
        assert isinstance(text, str) and len(text) > 20
        # Should mention invoice or policy/refund path without crashing.
        lowered = text.lower()
        assert any(token in lowered for token in ("inv-1042", "refund", "policy", "pro", "confirm"))

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
