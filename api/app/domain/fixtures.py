from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any


# Fixed demo clock so invoice age stays reproducible across restarts.
DEMO_AS_OF: date = date(2026, 11, 19)


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    email: str
    tier: str
    contract_status: str
    verified: bool = True


@dataclass(frozen=True)
class Invoice:
    id: str
    customer_id: str
    amount_cents: int
    currency: str
    status: str
    description: str
    charged_on: date
    is_duplicate: bool


@dataclass(frozen=True)
class PolicyDoc:
    id: str
    title: str
    tier: str
    version: str
    intent: str
    body: str


CUSTOMERS: dict[str, Customer] = {
    "cust_pro_001": Customer(
        id="cust_pro_001",
        name="Alex Rivera",
        email="alex.rivera@example.com",
        tier="Pro",
        contract_status="active",
        verified=True,
    ),
    "cust_basic_001": Customer(
        id="cust_basic_001",
        name="Jordan Lee",
        email="jordan.lee@example.com",
        tier="Basic",
        contract_status="active",
        verified=True,
    ),
}


INVOICES: dict[str, Invoice] = {
    "INV-1042": Invoice(
        id="INV-1042",
        customer_id="cust_pro_001",
        amount_cents=2900,
        currency="USD",
        status="posted",
        description="Duplicate Pro plan charge",
        charged_on=DEMO_AS_OF - timedelta(days=3),
        is_duplicate=True,
    ),
    "INV-1038": Invoice(
        id="INV-1038",
        customer_id="cust_pro_001",
        amount_cents=2900,
        currency="USD",
        status="posted",
        description="Monthly Pro plan",
        charged_on=DEMO_AS_OF - timedelta(days=3),
        is_duplicate=False,
    ),
    "INV-2001": Invoice(
        id="INV-2001",
        customer_id="cust_basic_001",
        amount_cents=1200,
        currency="USD",
        status="posted",
        description="Duplicate Basic plan charge",
        charged_on=DEMO_AS_OF - timedelta(days=5),
        is_duplicate=True,
    ),
}


POLICIES: list[PolicyDoc] = [
    PolicyDoc(
        id="pol_pro_billing_v3",
        title="Pro Billing & Refunds",
        tier="Pro",
        version="3.0",
        intent="billing_refund",
        body=(
            "Pro customers on an active contract may receive one full refund for a confirmed "
            "duplicate charge within 30 days of the charge date, up to $50.00 inclusive. "
            "Refunds require invoice verification and explicit customer confirmation. "
            "Citation: PRO-BILL-3.2."
        ),
    ),
    PolicyDoc(
        id="pol_basic_billing_v2",
        title="Basic Billing & Refunds",
        tier="Basic",
        version="2.0",
        intent="billing_refund",
        body=(
            "Basic tier duplicate-charge refunds are not automated. Create a human-review ticket "
            "with invoice evidence. Citation: BASIC-BILL-1.4."
        ),
    ),
    PolicyDoc(
        id="pol_setup_v1",
        title="Account Setup Guide",
        tier="Pro",
        version="1.0",
        intent="setup",
        body=(
            "To finish Pro setup: confirm billing email, invite teammates, and enable SSO under "
            "Settings → Security. Citation: SETUP-2.1."
        ),
    ),
    PolicyDoc(
        id="pol_escalation_v1",
        title="Escalation Policy",
        tier="*",
        version="1.0",
        intent="escalation",
        body=(
            "Escalate when the request is out of policy scope, evidence is conflicting, or the "
            "customer asks for a human. Include reason and relevant invoice/policy IDs. "
            "Citation: ESC-1.1."
        ),
    ),
]


def customer_to_dict(customer: Customer) -> dict[str, Any]:
    return asdict(customer)


def invoice_to_dict(invoice: Invoice) -> dict[str, Any]:
    data = asdict(invoice)
    data["charged_on"] = invoice.charged_on.isoformat()
    data["age_days"] = (DEMO_AS_OF - invoice.charged_on).days
    data["as_of"] = DEMO_AS_OF.isoformat()
    data["amount_display"] = f"${invoice.amount_cents / 100:.2f}"
    return data


def policy_to_dict(policy: PolicyDoc) -> dict[str, Any]:
    return asdict(policy)


def search_policies(query: str, tier: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """Phase 1: simple keyword ranking over seeded policy fixtures (vector RAG comes later)."""
    tokens = {t.lower() for t in query.replace(",", " ").split() if len(t) > 2}
    scored: list[tuple[int, PolicyDoc]] = []
    for policy in POLICIES:
        if tier and policy.tier not in {tier, "*"}:
            continue
        hay = f"{policy.title} {policy.intent} {policy.body}".lower()
        score = sum(1 for t in tokens if t in hay)
        if "duplicate" in query.lower() and "duplicate" in hay:
            score += 2
        if "refund" in query.lower() and "refund" in hay:
            score += 2
        if score > 0:
            scored.append((score, policy))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [policy_to_dict(p) for _, p in scored[:limit]]
