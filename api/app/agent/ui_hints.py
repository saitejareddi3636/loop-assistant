from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationEvent, MockReceipt
from app.domain.fixtures import INVOICES


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


def validate_confirmation_for_customer(
    confirmation: dict[str, Any],
    *,
    customer_id: str,
) -> dict[str, Any] | None:
    """Drop confirmations that no longer match invoice ownership / amounts."""
    invoice_id = str(confirmation.get("invoice_id") or "")
    invoice = INVOICES.get(invoice_id)
    if invoice is None or invoice.customer_id != customer_id:
        return None
    amount_cents = int(confirmation.get("amount_cents") or 0)
    if amount_cents != invoice.amount_cents:
        return None
    if not invoice.is_duplicate:
        return None
    return {
        **confirmation,
        "invoice_id": invoice.id,
        "amount_cents": invoice.amount_cents,
        "currency": invoice.currency,
        "amount_display": f"${invoice.amount_cents / 100:.2f}",
        "requires_explicit_confirm": True,
    }


async def build_assistant_ui(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    """Derive structured UI state from tool events for this run (no text regex)."""
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


_INVALIDATING_REFUND_ERRORS = frozenset(
    {
        "invoice_not_found",
        "customer_scope_mismatch",
        "customer_not_found",
        "inactive_contract",
        "tier_requires_manual_review",
        "not_a_duplicate_charge",
        "outside_refund_window",
        "amount_over_policy_limit",
    }
)


async def pending_confirmation_ui(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    customer_id: str,
) -> dict[str, Any]:
    """Pending refund confirmation that survives recoverable failures.

    Cleared on: successful refund, explicit cancel, invalidating refund errors,
    or invoice/customer scope no longer valid. Never restores a stale card.
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

    for row in rows:
        payload = dict(row.payload or {})
        if row.event_type == "confirmation.cancelled":
            last_confirm = None
            continue

        tool = str(payload.get("tool") or "")
        if row.event_type == "tool.completed" and tool == "get_invoice":
            last_invoice = payload
        if row.event_type == "tool.failed" and tool == "issue_mock_refund":
            err = str(payload.get("error") or "")
            if err in _INVALIDATING_REFUND_ERRORS:
                last_confirm = None
                continue
            conf = _confirmation_from_payloads(
                refund_failed=payload, invoice_payload=last_invoice
            )
            if conf:
                last_confirm = conf
        if (
            row.event_type == "tool.completed"
            and tool == "issue_mock_refund"
            and payload.get("ok") is True
        ):
            last_confirm = None

    if not last_confirm:
        return {}

    # Authoritative: any issued mock receipt for this customer+invoice clears pending UI.
    invoice_id = str(last_confirm.get("invoice_id") or "")
    existing_receipt = await session.scalar(
        select(MockReceipt).where(
            MockReceipt.customer_id == customer_id,
            MockReceipt.invoice_id == invoice_id,
        )
    )
    if existing_receipt is not None:
        return {}

    validated = validate_confirmation_for_customer(last_confirm, customer_id=customer_id)
    if not validated:
        return {}
    return {"confirmation": validated}
