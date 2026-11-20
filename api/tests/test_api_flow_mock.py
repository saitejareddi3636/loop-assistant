from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_health_and_chat_turn(client):
    health = (await client.get("/api/health")).json()
    assert health["database"] == "ok"
    assert health["llm_configured"] is True

    conv = (
        await client.post("/api/conversations", json={"customer_id": "cust_pro_001"})
    ).json()
    cid = conv["id"]

    turn = (
        await client.post(
            f"/api/conversations/{cid}/turns",
            json={
                "text": "I was charged twice on INV-1042. Can you help?",
                "client_turn_id": str(uuid.uuid4()),
            },
        )
    ).json()
    assert turn["status"] == "running"

    # Poll until assistant message exists.
    detail = None
    for _ in range(40):
        detail = (await client.get(f"/api/conversations/{cid}")).json()
        if any(m["role"] == "assistant" for m in detail["messages"]):
            break
        import asyncio

        await asyncio.sleep(0.1)
    assert detail is not None
    assert any(m["role"] == "assistant" for m in detail["messages"])
