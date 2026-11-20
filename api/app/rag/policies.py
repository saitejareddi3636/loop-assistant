from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class PolicyChunk:
    doc_id: str
    section_id: str
    title: str
    tier: str
    version: str
    status: str  # active | archived
    intent: str
    citation: str
    effective_from: date
    effective_to: date | None
    body: str
    is_exception: bool = False
    supersedes: str | None = None


# Six versioned fictional policies with an archived variant and tier exception.
POLICY_CHUNKS: list[PolicyChunk] = [
    PolicyChunk(
        doc_id="pol_pro_billing",
        section_id="PRO-BILL-3.2",
        title="Pro Billing & Refunds",
        tier="Pro",
        version="3.0",
        status="active",
        intent="billing_refund",
        citation="PRO-BILL-3.2",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        body=(
            "Pro customers on an active contract may receive one full refund for a confirmed "
            "duplicate charge within 30 days of the charge date, up to $50.00 inclusive. "
            "Refunds require invoice verification and explicit customer confirmation."
        ),
    ),
    PolicyChunk(
        doc_id="pol_pro_billing",
        section_id="PRO-BILL-2.1",
        title="Pro Billing & Refunds (Archived)",
        tier="Pro",
        version="2.0",
        status="archived",
        intent="billing_refund",
        citation="PRO-BILL-2.1",
        effective_from=date(2023, 1, 1),
        effective_to=date(2024, 12, 31),
        body=(
            "Archived: Pro duplicate refunds previously capped at $25. Do not apply this rule "
            "when a newer active version exists."
        ),
    ),
    PolicyChunk(
        doc_id="pol_basic_billing",
        section_id="BASIC-BILL-1.4",
        title="Basic Billing & Refunds",
        tier="Basic",
        version="2.0",
        status="active",
        intent="billing_refund",
        citation="BASIC-BILL-1.4",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        body=(
            "Basic tier duplicate-charge refunds are not automated. Create a human-review ticket "
            "with invoice evidence before promising any refund."
        ),
    ),
    PolicyChunk(
        doc_id="pol_contract_exceptions",
        section_id="PRO-EXC-1.1",
        title="Pro Contract Exception — Courtesy Credit",
        tier="Pro",
        version="1.0",
        status="active",
        intent="billing_refund",
        citation="PRO-EXC-1.1",
        effective_from=date(2025, 6, 1),
        effective_to=None,
        body=(
            "Exception: if a Pro customer experienced a confirmed billing system outage on the "
            "charge date, agents may offer a courtesy credit review ticket instead of an "
            "automated refund. Prefer PRO-BILL-3.2 for ordinary duplicate charges."
        ),
        is_exception=True,
        supersedes=None,
    ),
    PolicyChunk(
        doc_id="pol_cancellations",
        section_id="CANCEL-1.2",
        title="Cancellations",
        tier="*",
        version="1.0",
        status="active",
        intent="cancellation",
        citation="CANCEL-1.2",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        body=(
            "Subscriptions cancel at the end of the current billing period. Prepaid months are "
            "non-refundable unless a duplicate charge is proven."
        ),
    ),
    PolicyChunk(
        doc_id="pol_setup",
        section_id="SETUP-2.1",
        title="Account Setup Guide",
        tier="Pro",
        version="1.0",
        status="active",
        intent="setup",
        citation="SETUP-2.1",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        body=(
            "To finish Pro setup: confirm billing email, invite teammates, and enable SSO under "
            "Settings → Security."
        ),
    ),
    PolicyChunk(
        doc_id="pol_escalation",
        section_id="ESC-1.1",
        title="Escalation Policy",
        tier="*",
        version="1.0",
        status="active",
        intent="escalation",
        citation="ESC-1.1",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        body=(
            "Escalate when the request is out of policy scope, evidence is conflicting, confidence "
            "is below the retrieval threshold, or the customer asks for a human. Include reason "
            "and relevant invoice/policy IDs."
        ),
    ),
]


def chunk_to_dict(chunk: PolicyChunk) -> dict[str, Any]:
    data = asdict(chunk)
    data["effective_from"] = chunk.effective_from.isoformat()
    data["effective_to"] = chunk.effective_to.isoformat() if chunk.effective_to else None
    return data
