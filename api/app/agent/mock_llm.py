from __future__ import annotations

import json
import uuid
from typing import Any, Iterator, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field


class MockSupportChatModel(BaseChatModel):
    """Deterministic chat model for local Phase 1 testing without paid API credits.

    Exercises the same tool loop as a real LLM for the seeded Pro duplicate-charge flow.
    """

    bound_tools: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "mock-support"

    def bind_tools(self, tools: Sequence[BaseTool | dict[str, Any]], **kwargs: Any) -> MockSupportChatModel:
        serialized: list[dict[str, Any]] = []
        for tool in tools:
            if isinstance(tool, dict):
                serialized.append(tool)
            else:
                serialized.append({"name": tool.name})
        return self.model_copy(update={"bound_tools": serialized})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        yield self._decide(messages)

    def _tool_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "args": args,
            "id": f"call_{uuid.uuid4().hex[:10]}",
            "type": "tool_call",
        }

    def _latest_user_text(self, messages: list[BaseMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return str(message.content)
        return ""

    def _tool_results(self, messages: list[BaseMessage]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for message in messages:
            if isinstance(message, ToolMessage):
                try:
                    results[message.name or "tool"] = json.loads(str(message.content))
                except json.JSONDecodeError:
                    results[message.name or "tool"] = {"raw": message.content}
        return results

    def _customer_id(self, user_text: str) -> str:
        if "cust_basic_001" in user_text or "basic plan" in user_text or "basic tier" in user_text:
            return "cust_basic_001"
        return "cust_pro_001"

    def _decide(self, messages: list[BaseMessage]) -> AIMessage:
        # Ignore system prompt noise for routing.
        usable = [m for m in messages if not isinstance(m, SystemMessage)]
        user_text = self._latest_user_text(usable).lower()
        tools = self._tool_results(usable)
        names_done = set(tools.keys())
        customer_id = self._customer_id(user_text)

        # Basic-tier refunds must escalate (server also enforces this).
        if customer_id == "cust_basic_001" and any(
            w in user_text for w in ("refund", "charged twice", "duplicate", "inv-2001")
        ):
            if "create_ticket" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "create_ticket",
                            {
                                "reason": "Basic tier duplicate refund requires human review",
                                "customer_id": customer_id,
                                "references": ["INV-2001"] if "inv-2001" in user_text else [],
                            },
                        )
                    ],
                )
            ticket = tools.get("create_ticket", {}).get("ticket", {})
            return AIMessage(
                content=(
                    f"Basic-tier refunds need manual review. I opened human-review ticket "
                    f"{ticket.get('id', 'TCK-UNKNOWN')} for INV-2001."
                )
            )

        # Prompt injection / unsafe action — refuse without issuing refunds.
        if any(
            phrase in user_text
            for phrase in (
                "ignore previous",
                "ignore all",
                "disregard instructions",
                "system prompt",
                "refund everything",
                "refund all",
                "delete account",
                "wipe database",
            )
        ):
            return AIMessage(
                content=(
                    "I can't follow instructions that override safety rules or issue unconfirmed "
                    "refunds. If you want a refund on a specific duplicate invoice, say the invoice "
                    "id and explicitly confirm the amount."
                )
            )

        # Explicit human handoff request
        if any(phrase in user_text for phrase in ("speak to a human", "talk to a human", "real person", "human agent")):
            if "create_ticket" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "create_ticket",
                            {
                                "reason": "Customer requested human agent",
                                "customer_id": customer_id,
                                "references": [],
                            },
                        )
                    ],
                )
            ticket = tools.get("create_ticket", {}).get("ticket", {})
            return AIMessage(
                content=f"I've opened human-review ticket {ticket.get('id', 'TCK-UNKNOWN')} and a specialist will follow up."
            )

        # Subscription / tier questions
        if any(word in user_text for word in ("tier", "subscription", "what plan", "my plan", "account status")):
            if "verify_customer" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[self._tool_call("verify_customer", {"customer_id": customer_id})],
                )
            if "get_account" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[self._tool_call("get_account", {"customer_id": customer_id})],
                )
            account = (tools.get("get_account") or {}).get("account") or {}
            return AIMessage(
                content=(
                    f"Your account is on the {account.get('subscription_tier') or account.get('tier') or 'Pro'} "
                    f"tier with contract status {account.get('contract_status', 'active')}."
                )
            )

        # Unknown / invalid invoice ids
        if "inv-9999" in user_text or "inv-0000" in user_text:
            invoice_id = "INV-9999" if "inv-9999" in user_text else "INV-0000"
            if "verify_customer" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[self._tool_call("verify_customer", {"customer_id": customer_id})],
                )
            if "get_invoice" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "get_invoice",
                            {"invoice_id": invoice_id, "customer_id": customer_id},
                        )
                    ],
                )
            return AIMessage(
                content=(
                    f"I couldn't find invoice {invoice_id} on your account. Please double-check the id "
                    "(for example INV-1042) or ask me to open a human-review ticket."
                )
            )

        # Confirmation path (explicit customer confirm only)
        if any(word in user_text for word in ("yes", "confirm", "go ahead", "approve", "do it")):
            if "issue_mock_refund" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "issue_mock_refund",
                            {
                                "customer_id": customer_id,
                                "invoice_id": "INV-1042",
                                "confirmed": True,
                            },
                        )
                    ],
                )
            receipt = tools.get("issue_mock_refund", {})
            rid = ((receipt.get("receipt") or {}).get("id")) if isinstance(receipt, dict) else None
            return AIMessage(
                content=(
                    f"Done — mock refund for INV-1042 ($29.00) is issued"
                    + (f" (receipt {rid})." if rid else ".")
                    + " Policy citation: PRO-BILL-3.2."
                )
            )

        # Escalation / out of scope
        if any(word in user_text for word in ("coverage", "unrelated", "legal", "lawsuit")):
            if "create_ticket" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "create_ticket",
                            {
                                "reason": "Out-of-scope request requiring human review",
                                "customer_id": customer_id,
                                "references": [],
                            },
                        )
                    ],
                )
            ticket = tools.get("create_ticket", {}).get("ticket", {})
            return AIMessage(
                content=f"I've opened human-review ticket {ticket.get('id', 'TCK-UNKNOWN')} for this request."
            )

        # Billing investigation chain
        if "verify_customer" not in names_done:
            return AIMessage(
                content="",
                tool_calls=[self._tool_call("verify_customer", {"customer_id": customer_id})],
            )
        if "get_account" not in names_done:
            return AIMessage(
                content="",
                tool_calls=[self._tool_call("get_account", {"customer_id": customer_id})],
            )
        if "get_invoice" not in names_done:
            invoice_id = "INV-2001" if customer_id == "cust_basic_001" else "INV-1042"
            if "inv-1042" in user_text:
                invoice_id = "INV-1042"
            if "inv-2001" in user_text:
                invoice_id = "INV-2001"
            return AIMessage(
                content="",
                tool_calls=[
                    self._tool_call(
                        "get_invoice",
                        {"invoice_id": invoice_id, "customer_id": customer_id},
                    )
                ],
            )
        if "search_policy" not in names_done:
            query = (
                "duplicate charge refund policy"
                if any(w in user_text for w in ("charge", "refund", "invoice", "billing"))
                else user_text
            )
            tier = "Basic" if customer_id == "cust_basic_001" else "Pro"
            return AIMessage(
                content="",
                tool_calls=[
                    self._tool_call(
                        "search_policy",
                        {"query": query, "tier": tier},
                    )
                ],
            )

        policy = tools.get("search_policy", {})
        if policy.get("should_escalate") or policy.get("confident") is False:
            if "create_ticket" not in names_done:
                return AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "create_ticket",
                            {
                                "reason": policy.get("reason") or "Low-confidence policy match",
                                "customer_id": customer_id,
                                "references": [d.get("section_id") for d in policy.get("documents", [])],
                            },
                        )
                    ],
                )
            ticket = tools.get("create_ticket", {}).get("ticket", {})
            return AIMessage(
                content=(
                    f"I couldn't confidently ground an answer in policy, so I opened human-review "
                    f"ticket {ticket.get('id', 'TCK-UNKNOWN')}."
                )
            )

        docs = policy.get("documents") or []
        citation = docs[0].get("citation") if docs else "PRO-BILL-3.2"
        version = docs[0].get("version") if docs else "3.0"
        title = docs[0].get("title") if docs else "Pro Billing & Refunds"
        return AIMessage(
            content=(
                "I verified your Pro account and found a duplicate charge on INV-1042 for $29.00 "
                f"(3 days old). Under {title} v{version} ({citation}), you're eligible for "
                "one full mock refund within 30 days up to $50.\n\n"
                "Reply **yes** to confirm a $29.00 refund on INV-1042."
            )
        )
