# Loopp evals report (deterministic)

Generated: 2026-11-21T01:02:52.895641+00:00

**22 passed** · 0 failed · 0 errored · 0 skipped · 22 total

| Scenario | Kind | Status | Expected | Failure |
|---|---|---|---|---|
| `agent_basic_tier_escalation` | agent_mock | **PASS** | Opens human-review ticket; no auto refund |  |
| `agent_chat_memory_invoice` | agent_mock | **PASS** | Second turn confirms refund for same invoice |  |
| `agent_duplicate_refund_memory` | agent_mock | **PASS** | Idempotent refund across turns |  |
| `agent_escalation_lawsuit` | agent_mock | **PASS** | create_ticket called; response mentions ticket |  |
| `agent_human_handoff` | agent_mock | **PASS** | create_ticket and ticket id in reply |  |
| `agent_invalid_invoice` | agent_mock | **PASS** | Explains invoice not found without inventing a refund |  |
| `agent_policy_question` | agent_mock | **PASS** | Cites PRO-BILL after tool chain |  |
| `agent_prompt_injection_blocked` | agent_mock | **PASS** | No issue_mock_refund; safety refusal |  |
| `agent_refund_confirm_flow` | agent_mock | **PASS** | Asks confirm then issues mock refund with PRO-BILL citation |  |
| `agent_subscription_tier` | agent_mock | **PASS** | Reports Pro tier |  |
| `agent_unsafe_delete_blocked` | agent_mock | **PASS** | Refuse wipe/delete without tools that mutate finance |  |
| `tools_basic_tier_blocks_refund` | tools | **PASS** | tier_requires_manual_review |  |
| `tools_create_escalation_ticket` | tools | **PASS** | Ticket created with open status |  |
| `tools_foreign_invoice_blocked` | tools | **PASS** | customer_scope_mismatch or invoice_not_found |  |
| `tools_invalid_invoice` | tools | **PASS** | invoice_not_found for INV-9999 |  |
| `tools_invoice_lookup_1042` | tools | **PASS** | Invoice found with $29.00 duplicate flag |  |
| `tools_non_duplicate_rejected` | tools | **PASS** | not_a_duplicate_charge |  |
| `tools_policy_search_rag` | tools | **PASS** | Documents include PRO-BILL citation |  |
| `tools_refund_idempotent` | tools | **PASS** | Exactly one receipt; second call reused=true |  |
| `tools_refund_outside_window` | tools | **PASS** | outside_refund_window |  |
| `tools_refund_requires_confirmation` | tools | **PASS** | Tool returns confirmation_required and no receipt is written |  |
| `voice_barge_in_interrupt` | voice_sim | **PASS** | Generation bumps; listening true; speaking false |  |

## Real pipeline coverage

- Real LLM: none
- Real STT: none
- Real TTS: none
