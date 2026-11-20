from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MockReceipt
from app.domain.fixtures import CUSTOMERS, DEMO_AS_OF, INVOICES, invoice_to_dict


async def issue_mock_refund(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    customer_id: str,
    invoice_id: str,
) -> dict[str, Any]:
    customer = CUSTOMERS.get(customer_id)
    invoice = INVOICES.get(invoice_id)
    if customer is None:
        return {"ok": False, "error": "customer_not_found"}
    if invoice is None or invoice.customer_id != customer_id:
        return {"ok": False, "error": "invoice_not_found"}
    if customer.contract_status != "active":
        return {"ok": False, "error": "inactive_contract"}
    if customer.tier != "Pro":
        return {
            "ok": False,
            "error": "tier_requires_manual_review",
            "message": "Basic tier refunds must be escalated to human review.",
        }
    if not invoice.is_duplicate:
        return {"ok": False, "error": "not_a_duplicate_charge"}

    age_days = (DEMO_AS_OF - invoice.charged_on).days
    if age_days > 30:
        return {"ok": False, "error": "outside_refund_window", "age_days": age_days}
    if invoice.amount_cents > 5000:
        return {"ok": False, "error": "amount_over_policy_limit", "limit_cents": 5000}

    existing = await session.scalar(
        select(MockReceipt).where(
            MockReceipt.customer_id == customer_id,
            MockReceipt.invoice_id == invoice_id,
        )
    )
    if existing is not None:
        return {
            "ok": True,
            "reused": True,
            "receipt": {
                "id": str(existing.id),
                "invoice_id": existing.invoice_id,
                "amount_cents": existing.amount_cents,
                "currency": existing.currency,
                "status": existing.status,
            },
            "invoice": invoice_to_dict(invoice),
        }

    receipt = MockReceipt(
        conversation_id=conversation_id,
        customer_id=customer_id,
        invoice_id=invoice_id,
        amount_cents=invoice.amount_cents,
        currency=invoice.currency,
        status="issued",
        meta={"policy": "PRO-BILL-3.2", "as_of": DEMO_AS_OF.isoformat()},
    )
    session.add(receipt)
    await session.flush()
    return {
        "ok": True,
        "reused": False,
        "receipt": {
            "id": str(receipt.id),
            "invoice_id": receipt.invoice_id,
            "amount_cents": receipt.amount_cents,
            "currency": receipt.currency,
            "status": receipt.status,
        },
        "invoice": invoice_to_dict(invoice),
    }
