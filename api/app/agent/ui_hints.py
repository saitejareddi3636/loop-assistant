from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationEvent


async def build_assistant_ui(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    """Derive structured UI state from tool events for this run (no text regex).

    Confirmation cards appear only when ``issue_mock_refund`` returns
    ``confirmation_required`` — never from reply text or co-occurrence of
    invoice/policy lookups (those also run for pure policy Q&A).
    """
    rows = (
        await session.scalars(
            select(ConversationEvent)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.run_id == run_id,
            )
            .order_by(ConversationEvent.sequence.asc())
        )
    ).all()

    completed: dict[str, dict[str, Any]] = {}
    failed: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = dict(row.payload or {})
        tool = str(payload.get("tool") or "")
        if not tool:
            continue
        if row.event_type == "tool.completed":
            completed[tool] = payload
        elif row.event_type == "tool.failed":
            failed[tool] = payload

    ui: dict[str, Any] = {}

    refund_failed = failed.get("issue_mock_refund") or {}
    invoice_payload = completed.get("get_invoice") or {}

    if refund_failed.get("error") == "confirmation_required":
        invoice_id = str(
            refund_failed.get("invoice_id")
            or invoice_payload.get("invoice_id")
            or ""
        )
        amount_cents = int(
            refund_failed.get("amount_cents")
            if refund_failed.get("amount_cents") is not None
            else invoice_payload.get("amount_cents")
            or 0
        )
        currency = str(
            refund_failed.get("currency")
            or invoice_payload.get("currency")
            or "USD"
        )
        if invoice_id and amount_cents:
            ui["confirmation"] = {
                "kind": "refund",
                "invoice_id": invoice_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "amount_display": f"${amount_cents / 100:.2f}",
                "requires_explicit_confirm": True,
            }

    if completed.get("issue_mock_refund", {}).get("ok") is True:
        ui.pop("confirmation", None)
        receipt = completed.get("issue_mock_refund") or {}
        if receipt.get("ok"):
            ui["refund_receipt"] = {"ok": True, **{k: v for k, v in receipt.items() if k != "tool"}}

    ticket_payload = completed.get("create_ticket") or {}
    ticket_id = ticket_payload.get("ticket_id")
    if ticket_id:
        ui["escalation"] = {
            "ticket_id": str(ticket_id),
            "status": "open",
        }

    return ui
