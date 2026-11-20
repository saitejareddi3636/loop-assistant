# Evals verification log (2026-11-20)

Evidence from measured local runs on Darwin arm64. Do not treat unchecked suites as passed.

## 1. Scenario pass / fail

| Suite | Ran | Passed | Failed | Notes |
|-------|-----|--------|--------|-------|
| `deterministic` | 22 | **22** | 0 | tools + agent_mock + voice_sim |
| `live` (full) | 5 | 2 then rate-limited | 3 | Groq TPM; failures preserved |
| `live` (rerun failed ids) | 3 | **3** | 0 | After cooldown + apostrophe fix |
| `voice` (subset) | 3 | **3** | 0 | Real Moonshine STT + Groq + Pocket TTS (`voice_stt_invoice_clear`, `voice_noisy_short_ack`, `voice_refund_confirm_e2e`) |

Total authored scenarios: **30** (10 tools, 11 agent_mock, 5 agent_live, 3 voice_live, 1 voice_sim).

## 2. Real pipeline usage

| Component | Used in |
|-----------|---------|
| Moonshine Tiny STT | `voice_stt_invoice_clear`, `voice_noisy_short_ack`, `voice_refund_confirm_e2e` |
| LangGraph + tools + RAG | All `agent_*` and `voice_*` (and tool events on `tools_*`) |
| Groq LLM | All `agent_live` + `voice_live` |
| Pocket TTS | All `voice_live` |
| Mock LLM only | `agent_mock` / deterministic CI |
| No LLM | `tools_*`, `voice_sim` |

Deterministic CI never claims live STT/LLM/TTS.

## 3. Bugs discovered

1. **Mock LLM hardcoded `cust_pro_001`** — Basic-tier sessions got `customer_scope_mismatch` then invented Pro refund eligibility.  
   **Fix:** `api/app/agent/mock_llm.py` now scopes customer id from utterance and escalates Basic refunds via `create_ticket`.
2. **Live suite silently stayed on mock** — `evals/.env` set `LLM_PROVIDER=mock` and `setdefault` did not override.  
   **Fix:** `evals/harness/env.py` forces Groq provider/model for live/voice.
3. **Unicode apostrophe assertion miss** — model replied `can’t`; ASCII `can't` assertion failed despite correct refusal.  
   **Fix:** normalize curly quotes in `evals/harness/assertions.py`.
4. **Groq 429 rate limits** — caused false live failures mid-suite.  
   **Mitigation:** longer retries, inter-scenario pause; failures kept under `failures/_runs/`.

## 4. Fixes verified

- Deterministic suite: **22/22 PASS** after mock Basic-tier fix.
- Existing `api` pytest: **14/14 PASS**.
- Live rerun of `live_prompt_injection`, `live_rag_citations`, `live_refund_confirm`: **3/3 PASS**.
- Voice subset with real STT/LLM/TTS: **3/3 PASS**.

## 5. Remains untested / manual

- Full `voice` suite back-to-back under tight Groq TPM without pauses.
- AI judge enabled on every live turn (token-heavy; optional via unset `EVALS_DISABLE_JUDGE`).
- Production Oracle VM (intentionally not targeted).
- Real telephony noise / accents (fixtures are `say`/synthetic).
- Concurrent multi-session load / WebSocket browser clients (harness calls production adapters without browser).
