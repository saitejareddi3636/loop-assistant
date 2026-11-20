from __future__ import annotations

import pytest

from app.rag.retrieve import hybrid_search_policies


@pytest.mark.asyncio
async def test_hybrid_search_returns_pro_billing_citation(session):
    result = await hybrid_search_policies(
        session,
        query="I was charged twice, can I get a duplicate refund?",
        tier="Pro",
    )
    assert result["ok"] is True
    assert result["count"] >= 1
    assert result["confident"] is True
    citations = {doc["citation"] for doc in result["documents"]}
    assert "PRO-BILL-3.2" in citations
    # Archived policy must not appear as an active hit.
    assert all(doc["status"] == "active" for doc in result["documents"])
    assert all(doc["version"] != "2.0" or doc["citation"] != "PRO-BILL-2.1" for doc in result["documents"])


@pytest.mark.asyncio
async def test_low_confidence_query_flags_escalation(session):
    result = await hybrid_search_policies(
        session,
        query="quantum spaceship warranty for my pet rock",
        tier="Pro",
    )
    assert result["ok"] is True
    assert result["should_escalate"] is True
    assert result["confident"] is False
