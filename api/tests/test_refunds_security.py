from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import MockReceipt
from app.domain.refunds import issue_mock_refund


@pytest.mark.asyncio
async def test_refund_requires_pro_duplicate_and_is_idempotent(session):
    # Clear any prior demo receipt so the first issue is a fresh write.
    existing_rows = (
        await session.scalars(
            select(MockReceipt).where(
                MockReceipt.customer_id == "cust_pro_001",
                MockReceipt.invoice_id == "INV-1042",
            )
        )
    ).all()
    for row in existing_rows:
        await session.delete(row)
    await session.commit()

    conversation_id = uuid.uuid4()
    first = await issue_mock_refund(
        session,
        conversation_id=conversation_id,
        customer_id="cust_pro_001",
        invoice_id="INV-1042",
    )
    await session.commit()
    assert first["ok"] is True
    assert first["reused"] is False

    second = await issue_mock_refund(
        session,
        conversation_id=conversation_id,
        customer_id="cust_pro_001",
        invoice_id="INV-1042",
    )
    await session.commit()
    assert second["ok"] is True
    assert second["reused"] is True
    assert second["receipt"]["id"] == first["receipt"]["id"]

    rows = (
        await session.scalars(
            select(MockReceipt).where(
                MockReceipt.customer_id == "cust_pro_001",
                MockReceipt.invoice_id == "INV-1042",
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_refund_rejects_basic_tier_and_foreign_invoice(session):
    basic = await issue_mock_refund(
        session,
        conversation_id=uuid.uuid4(),
        customer_id="cust_basic_001",
        invoice_id="INV-2001",
    )
    assert basic["ok"] is False
    assert basic["error"] == "tier_requires_manual_review"

    foreign = await issue_mock_refund(
        session,
        conversation_id=uuid.uuid4(),
        customer_id="cust_pro_001",
        invoice_id="INV-2001",
    )
    assert foreign["ok"] is False
    assert foreign["error"] == "invoice_not_found"

    non_dup = await issue_mock_refund(
        session,
        conversation_id=uuid.uuid4(),
        customer_id="cust_pro_001",
        invoice_id="INV-1038",
    )
    assert non_dup["ok"] is False
    assert non_dup["error"] == "not_a_duplicate_charge"
