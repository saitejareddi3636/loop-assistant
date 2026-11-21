from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationEvent


def _confirmation_from_payloads(
    *,
    refund_failed: dict[str, Any],
    invoice_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if refund_failed.get("error") != "confirmation_required":
        return None
    invoice_id = str(
        refund_failed.get("invoice_id") or invoice_payload.get("invoice_id") or ""
    )
    amount_cents = int(
        refund_failed.get("amount_cents")
        if refund_failed.get("amount_cents") is not None
        else invoice_payload.get("amount_cents")
        or 0
    )
    currency = str(
        refund_failed.get("currency") or invoice_payload.get("currency") or "USD"
    )
    if not invoice_id or not amount_cents:
        return None
    return {
        "kind": "refund",
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "currency": currency,
        "amount_display": f"${amount_cents / 100:.2f}",
        "requires_explicit_confirm": True,
    }


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
    confirmation = _confirmation_from_payloads(
        refund_failed=refund_failed, invoice_payload=invoice_payload
    )
    if confirmation:
        ui["confirmation"] = confirmation

    if completed.get("issue_mock_refund", {}).get("ok") is True:
        ui.pop("confirmation", None)
        receipt = completed.get("issue_mock_refund") or {}
        if receipt.get("ok"):
            ui["refund_receipt"] = {
                "ok": True,
                **{k: v for k, v in receipt.items() if k != "tool"},
            }

    ticket_payload = completed.get("create_ticket") or {}
    ticket_id = ticket_payload.get("ticket_id")
    if ticket_id:
        ui["escalation"] = {
            "ticket_id": str(ticket_id),
            "status": "open",
        }

    return ui


async def pending_confirmation_ui(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
) -> dict[str, Any]:
    """Pending refund confirmation for the conversation (survives recoverable turn failures).

    Uses tool events across runs: last ``confirmation_required`` wins unless a later
    successful ``issue_mock_refund`` cleared it.
    """
    rows = (
        await session.scalars(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.sequence.asc())
        )
    ).all()

    last_confirm: dict[str, Any] | None = None
    last_invoice: dict[str, Any] = {}
    refund_completed_after = False

    for row in rows:
        payload = dict(row.payload or {})
        tool = str(payload.get("tool") or "")
        if row.event_type == "tool.completed" and tool == "get_invoice":
            last_invoice = payload
        if row.event_type == "tool.failed" and tool == "issue_mock_refund":
            conf = _confirmation_from_payloads(
                refund_failed=payload, invoice_payload=last_invoice
            )
            if conf:
                last_confirm = conf
                refund_completed_after = False
        if (
            row.event_type == "tool.completed"
            and tool == "issue_mock_refund"
            and payload.get("ok") is True
        ):
            refund_completed_after = True
            last_confirm = None

    if last_confirm and not refund_completed_after:
        return {"confirmation": last_confirm}
    return {}
