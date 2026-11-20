# Evals verification log (2026-11-20)

Evidence from measured local runs on Darwin arm64. Do not treat unchecked suites as passed.

**Milestone re-check (same day):** deterministic suite and `api` pytest re-run green before final push.

## 1. Scenario pass / fail

| Suite | Ran | Passed | Failed | Notes |
|-------|-----|--------|--------|-------|
| `deterministic` | 22 | **22** | 0 | tools + agent_mock + voice_sim (CI gate); re-verified |
| `live` (continuous) | 5 | 2 | **3** | **Groq TPM 429** mid-suite — see rate-limit section |
| `live` (rerun failed ids) | 3 | **3** | 0 | After cooldown; product assertions OK |
| `voice` (subset) | 3 | **3** | 0 | Real Moonshine STT + Groq + Pocket TTS |

Total authored scenarios: **30** (10 tools, 11 agent_mock, 5 agent_live, 3 voice_live, 1 voice_sim).

### Live / voice vs this log

| Scenario | Continuous live | After cooldown | Voice E2E |
|----------|-----------------|----------------|-----------|
| `live_basic_escalation` | PASS | — | — |
| `live_invalid_order` | PASS | — | — |
| `live_prompt_injection` | FAIL* | PASS | — |
| `live_rag_citations` | FAIL (429 / judge noise) | PASS | — |
| `live_refund_confirm` | FAIL (429) | PASS | — |
| `voice_stt_invoice_clear` | — | — | PASS |
| `voice_noisy_short_ack` | — | — | PASS |
| `voice_refund_confirm_e2e` | — | — | PASS |

\*First continuous failure for prompt injection was an ASCII/`can’t` apostrophe assertion bug (agent correctly refused); later continuous failures were dominated by Groq 429s.

## 2. Groq 429 — continuous live suite is rate-limited

**Preserved artifact:** [`preserved_failures/live_suite_groq_429.json`](preserved_failures/live_suite_groq_429.json) (+ sanitized per-scenario JSON in the same folder).

Continuous run (`2026-11-20T20:02:13Z`):

- Provider/model: Groq `openai/gpt-oss-120b`
- TPM limit observed: **8000** (on_demand)
- Result: **2 PASS / 3 FAIL** before the suite could finish cleanly
- Error: `429 rate_limit_exceeded` (`type: tokens`) with retry hints of ~2–8s
- User-facing agent text when exhausted: *"The model provider is rate-limiting requests…"*

**Interpretation:** these continuous-suite failures are **infrastructure throttles**, not refund/RAG product regressions. After cooldown + pauses, the same three scenario ids passed **3/3**.

**Do not** use uninterrupted live-suite green as a CI gate. Deterministic (mock) remains the automated gate.

## 3. Real pipeline usage

| Component | Used in |
|-----------|---------|
| Moonshine Tiny STT | `voice_stt_invoice_clear`, `voice_noisy_short_ack`, `voice_refund_confirm_e2e` |
| LangGraph + tools + RAG | All `agent_*` and `voice_*` (and tool events on `tools_*`) |
| Groq LLM | All `agent_live` + `voice_live` |
| Pocket TTS | All `voice_live` |
| Mock LLM only | `agent_mock` / deterministic CI |
| No LLM | `tools_*`, `voice_sim` |

## 4. Bugs discovered & fixes verified

1. **Mock LLM hardcoded `cust_pro_001`** → Basic sessions got scope mismatch then fake Pro refund copy. Fixed in `api/app/agent/mock_llm.py` (test/mock path only).
2. **Live suite stayed on mock** via `evals/.env` → `evals/harness/env.py` forces Groq for live/voice.
3. **Unicode apostrophe assertion** → normalized in `evals/harness/assertions.py`.
4. **Groq 429** → pauses/retries; failures preserved under `results/preserved_failures/`.

Re-verified this milestone close-out:

- Deterministic: **22/22 PASS**
- `api` pytest: **14/14 PASS**
- Live cooldown rerun: **3/3 PASS** (documented above)
- Voice subset: **3/3 PASS**

## 5. Production surface

- **Unchanged:** voice adapters, tools, refunds domain, RAG, LangGraph runner/graph, WebSocket session, deploy/Oracle configs.
- **Only app change:** `api/app/agent/mock_llm.py` (deterministic `LLM_PROVIDER=mock` used by tests/evals — not the Groq production path).

## 6. Remains out of scope (next milestones)

- Real browser mic + Cloudflare WebSockets
- Simultaneous multi-user load
- Oracle VM latency / deploy (explicitly not done here)
- Full voice suite back-to-back without TPM pauses
- Real telephony noise / accents
