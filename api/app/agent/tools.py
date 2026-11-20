from __future__ import annotations

import uuid
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EscalationTicket
from app.domain.fixtures import (
    CUSTOMERS,
    INVOICES,
    customer_to_dict,
    invoice_to_dict,
)
from app.domain.refunds import issue_mock_refund
from app.events.bus import EventBus
from app.rag.retrieve import hybrid_search_policies


class ToolContext:
    def __init__(
        self,
        *,
        session: AsyncSession,
        event_bus: EventBus,
        conversation_id: uuid.UUID,
        run_id: uuid.UUID,
        customer_id: str,
    ) -> None:
        self.session = session
        self.event_bus = event_bus
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.customer_id = customer_id


class VerifyCustomerArgs(BaseModel):
    customer_id: str = Field(description="Demo customer id to verify, e.g. cust_pro_001")


class GetAccountArgs(BaseModel):
    customer_id: str = Field(description="Verified customer id")


class GetInvoiceArgs(BaseModel):
    invoice_id: str = Field(description="Invoice id such as INV-1042")
    customer_id: str = Field(description="Owner customer id")


class SearchPolicyArgs(BaseModel):
    query: str = Field(description="Natural language policy query")
    tier: str | None = Field(default=None, description="Optional subscription tier filter")


class IssueRefundArgs(BaseModel):
    customer_id: str = Field(description="Verified customer id")
    invoice_id: str = Field(description="Invoice to refund, e.g. INV-1042")
    confirmed: bool = Field(description="True only after the customer explicitly confirms")


class CreateTicketArgs(BaseModel):
    reason: str = Field(description="Why this needs human review")
    customer_id: str = Field(description="Customer id")
    references: list[str] = Field(default_factory=list, description="Invoice/policy ids")


async def _emit_tool(
    ctx: ToolContext,
    *,
    name: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    event_type = "tool.started" if status == "started" else (
        "tool.completed" if status == "completed" else "tool.failed"
    )
    await ctx.event_bus.publish(
        ctx.session,
        conversation_id=ctx.conversation_id,
        run_id=ctx.run_id,
        event_type=event_type,
        payload={"tool": name, "status": status, **(detail or {})},
    )
    await ctx.session.commit()


def build_tools(ctx: ToolContext) -> list[StructuredTool]:
    async def verify_customer(customer_id: str) -> dict[str, Any]:
        await _emit_tool(ctx, name="verify_customer", status="started", detail={"customer_id": customer_id})
        if customer_id != ctx.customer_id:
            result = {
                "ok": False,
                "error": "customer_scope_mismatch",
                "message": "Can only verify the signed-in sandbox customer for this session.",
            }
            await _emit_tool(ctx, name="verify_customer", status="failed", detail=result)
            return result
        customer = CUSTOMERS.get(customer_id)
        if customer is None:
            result = {"ok": False, "error": "unknown_customer"}
            await _emit_tool(ctx, name="verify_customer", status="failed", detail=result)
            return result
        result = {"ok": True, "customer": customer_to_dict(customer), "verified": customer.verified}
        await _emit_tool(ctx, name="verify_customer", status="completed", detail={"customer_id": customer_id})
        return result

    async def get_account(customer_id: str) -> dict[str, Any]:
        await _emit_tool(ctx, name="get_account", status="started", detail={"customer_id": customer_id})
        if customer_id != ctx.customer_id:
            result = {"ok": False, "error": "customer_scope_mismatch"}
            await _emit_tool(ctx, name="get_account", status="failed", detail=result)
            return result
        customer = CUSTOMERS.get(customer_id)
        if customer is None:
            result = {"ok": False, "error": "unknown_customer"}
            await _emit_tool(ctx, name="get_account", status="failed", detail=result)
            return result
        result = {
            "ok": True,
            "account": {
                **customer_to_dict(customer),
                "subscription_tier": customer.tier,
                "contract_status": customer.contract_status,
            },
        }
        await _emit_tool(ctx, name="get_account", status="completed", detail={"tier": customer.tier})
        return result

    async def get_invoice(invoice_id: str, customer_id: str) -> dict[str, Any]:
        await _emit_tool(
            ctx,
            name="get_invoice",
            status="started",
            detail={"invoice_id": invoice_id, "customer_id": customer_id},
        )
        if customer_id != ctx.customer_id:
            result = {"ok": False, "error": "customer_scope_mismatch"}
            await _emit_tool(ctx, name="get_invoice", status="failed", detail=result)
            return result
        invoice = INVOICES.get(invoice_id)
        if invoice is None or invoice.customer_id != customer_id:
            result = {"ok": False, "error": "invoice_not_found"}
            await _emit_tool(ctx, name="get_invoice", status="failed", detail=result)
            return result
        result = {"ok": True, "invoice": invoice_to_dict(invoice)}
        await _emit_tool(
            ctx,
            name="get_invoice",
            status="completed",
            detail={"invoice_id": invoice_id, "amount_cents": invoice.amount_cents},
        )
        return result

    async def search_policy(query: str, tier: str | None = None) -> dict[str, Any]:
        await _emit_tool(ctx, name="search_policy", status="started", detail={"query": query, "tier": tier})
        result = await hybrid_search_policies(ctx.session, query=query, tier=tier)
        status = "completed" if result.get("ok") else "failed"
        await _emit_tool(
            ctx,
            name="search_policy",
            status=status,
            detail={
                "count": result.get("count", 0),
                "confident": result.get("confident"),
                "should_escalate": result.get("should_escalate"),
                "ids": [d.get("section_id") for d in result.get("documents", [])],
            },
        )
        return result

    async def issue_refund(customer_id: str, invoice_id: str, confirmed: bool) -> dict[str, Any]:
        await _emit_tool(
            ctx,
            name="issue_mock_refund",
            status="started",
            detail={"invoice_id": invoice_id, "confirmed": confirmed},
        )
        if customer_id != ctx.customer_id:
            result = {"ok": False, "error": "customer_scope_mismatch"}
            await _emit_tool(ctx, name="issue_mock_refund", status="failed", detail=result)
            return result
        if not confirmed:
            result = {
                "ok": False,
                "error": "confirmation_required",
                "message": "Ask the customer to confirm the refund amount and invoice before calling again.",
            }
            await _emit_tool(ctx, name="issue_mock_refund", status="failed", detail=result)
            return result
        result = await issue_mock_refund(
            ctx.session,
            conversation_id=ctx.conversation_id,
            customer_id=customer_id,
            invoice_id=invoice_id,
        )
        await ctx.session.commit()
        status = "completed" if result.get("ok") else "failed"
        await _emit_tool(ctx, name="issue_mock_refund", status=status, detail={"ok": result.get("ok")})
        return result

    async def create_ticket(reason: str, customer_id: str, references: list[str] | None = None) -> dict[str, Any]:
        await _emit_tool(ctx, name="create_ticket", status="started", detail={"reason": reason})
        if customer_id != ctx.customer_id:
            result = {"ok": False, "error": "customer_scope_mismatch"}
            await _emit_tool(ctx, name="create_ticket", status="failed", detail=result)
            return result
        ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
        ticket = EscalationTicket(
            id=ticket_id,
            conversation_id=ctx.conversation_id,
            customer_id=customer_id,
            reason=reason,
            references=references or [],
            status="open",
        )
        ctx.session.add(ticket)
        await ctx.session.commit()
        result = {
            "ok": True,
            "ticket": {
                "id": ticket_id,
                "customer_id": customer_id,
                "reason": reason,
                "references": references or [],
                "status": "open",
            },
        }
        await _emit_tool(ctx, name="create_ticket", status="completed", detail={"ticket_id": ticket_id})
        return result

    def tool(
        name: str,
        description: str,
        args_schema: type[BaseModel],
        coroutine: Callable[..., Any],
    ) -> StructuredTool:
        return StructuredTool.from_function(
            name=name,
            description=description,
            args_schema=args_schema,
            coroutine=coroutine,
        )

    return [
        tool(
            "verify_customer",
            "Verify the signed-in demo customer identity before account lookups.",
            VerifyCustomerArgs,
            verify_customer,
        ),
        tool(
            "get_account",
            "Fetch subscription tier and contract status for a verified customer.",
            GetAccountArgs,
            get_account,
        ),
        tool(
            "get_invoice",
            "Look up an invoice owned by the customer and whether it is a duplicate charge.",
            GetInvoiceArgs,
            get_invoice,
        ),
        tool(
            "search_policy",
            "Hybrid vector+keyword search over versioned support policies with confidence scores and citations.",
            SearchPolicyArgs,
            search_policy,
        ),
        tool(
            "issue_mock_refund",
            "Issue a mock refund for an eligible Pro duplicate invoice after explicit confirmation. Server enforces policy.",
            IssueRefundArgs,
            issue_refund,
        ),
        tool(
            "create_ticket",
            "Create a persisted human-review ticket for low-confidence or out-of-scope requests.",
            CreateTicketArgs,
            create_ticket,
        ),
    ]


SYSTEM_PROMPT = """You are Loopp's customer support AI agent for a fictional sandbox.

You dynamically choose tools. Never invent invoices, tiers, receipts, or policy clauses.

Demo sandbox:
- Default signed-in Pro customer: cust_pro_001 (Alex Rivera)
- Duplicate charge example: INV-1042 for $29.00 (3 days old)
- Pro policy PRO-BILL-3.2 allows one full mock refund within 30 days, up to $50, active contract
- Basic tier refunds must escalate via create_ticket

Tooling rules:
1. Prefer tools for facts. Typical billing path: verify_customer → get_account → get_invoice → search_policy.
2. When search_policy returns confident=false or should_escalate=true, call create_ticket and explain.
3. Never call issue_mock_refund with confirmed=true until the customer clearly confirms invoice + amount.
4. Always cite policy title, section/citation id, and version when answering from retrieval.
5. Keep replies concise. If upstream tools fail, explain and offer escalation.
6. Authorization and refund eligibility are enforced server-side — trust tool error codes.
"""
