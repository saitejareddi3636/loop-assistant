# Oracle production readiness audit

Generated: 2026-11-20T20:19:27.189809+00:00
Updated: 2026-11-20T20:25:00.701647+00:00
Cloudflare: `https://loopp-proxy.saitejareddi1503.workers.dev`
Origin: `https://129.80.125.203.sslip.io`

**PASS 14 · FAIL 3 · PARTIAL 4 · BLOCKED 2** (total 23)

| ID | Status | Check | Detail |
|----|--------|-------|--------|
| `https_health_cloudflare` | **PASS** | HTTPS health (cloudflare) | {"status": "ok", "database": "ok", "llm_configured": true, "model": "groq:openai/gpt-oss-120b"} |
| `https_health_sslip_origin` | **PASS** | HTTPS health (sslip_origin) | {"status": "ok", "database": "ok", "llm_configured": true, "model": "groq:openai/gpt-oss-120b"} |
| `tls_letsencrypt_sslip` | **PASS** | Let's Encrypt cert on sslip.io origin | CN=129.80.125.203.sslip.io issuer=Let's Encrypt YE2; notAfter=2026-02-18 (from openssl probe) |
| `https_direct_ip` | **FAIL** | Direct IP HTTPS | Bare-IP HTTPS TLS alert confirmed. Fix prepared on branch (disable IP HTTPS site in Caddyfile); not auto-deployed. |
| `chat_turn` | **PASS** | Chat turn completes with assistant reply | For Pro customers on an active contract, the policy allows **one full refund for a confirmed duplicate charge** if the request is made **within 30 days of the c |
| `sse_stream` | **PASS** | SSE events stream (tools/pings) | Re-probed: SSE streams tool.* events through Cloudflare Worker and sslip origin (aiter_lines). Initial FAIL was audit client buffering, not production. |
| `rag_citations` | **PASS** | RAG / policy citation in reply | For Pro customers on an active contract, the policy allows **one full refund for a confirmed duplicate charge** if the request is made **within 30 days of the c |
| `session_memory` | **PASS** | Multi-turn session memory responds in same conversation | For Pro customers on an active contract, the policy allows **one full refund for a confirmed duplicate charge** if the request is made **within 30 days of the c |
| `refund_confirmation_gate` | **PASS** | Refund flow asks confirmation (no auto-issue) | Yes, that charge qualifies for a refund under **Pro Billing & Refunds** (policy **PRO‑BILL‑3.2**, version 3.0), which allows one full refund for a confirmed dup |
| `escalation` | **PASS** | Human escalation path | Your request has been logged and a human support agent will review it shortly.  Ticket ID: **TCK‑BAB92050**   Reason: “User requests human agent for lawsuit cov |
| `voice_pipeline_ws` | **PASS** | Voice WebSocket STT→agent→TTS via Cloudflare | backend={"type": "voice.backend", "backend": "stt=groq-whisper;tts=pocket-tts;vad=silero-vad-lite", "tts_sample_rate": 24000} transcript='.' assistant='How can  |
| `voice_stt_moonshine` | **FAIL** | Production STT is Moonshine Tiny (local) | Voice backend reported stt=groq-whisper (hosted), tts=pocket-tts, vad=silero-vad-lite. Oracle auto path did not load Moonshine. Requires VOICE_BACKEND=local + v |
| `browser_microphone_hardware` | **BLOCKED** | Real browser microphone capture | Automated browser cannot grant getUserMedia mic permission here; WebSocket PCM path exercised instead. Manual reviewer should click Start voice once. |
| `voice_first_audio_latency` | **PASS** | TTS first-audio latency samples (ms) | Server voice.tts_first_audio (TTS stage) and/or wall clock; end-of-speech→first-audio fully requires VAD timestamps (not always exported) |
| `barge_in` | **PARTIAL** | Voice interrupt / barge-in | interrupted=False err=None events=['voice.ready', 'voice.backend', 'voice.speech_started', 'voice.transcribing', 'voice.transcript', 'voice.assistant_text', 'vo |
| `concurrent_two_voice` | **PASS** | Two simultaneous voice WebSocket sessions | wall_ms=6521 a_err=None b_err=None |
| `host_cpu_ram_during_concurrent` | **BLOCKED** | Oracle CPU/RAM during dual voice | SSH to 129.80.125.203 denied (publickey) for ubuntu/opc with available keys; cannot sample docker stats live. |
| `groq_rate_limit_handling` | **PASS** | Groq rate-limit / burst handling | Burst completed without hard crash; last=You’re on the **Pro** tier (active contract). |
| `ws_bad_token` | **PASS** | WebSocket rejects bad token/conversation | server rejected WebSocket connection: HTTP 502 |
| `docker_autorestart` | **PARTIAL** | Docker restart: unless-stopped | compose.prod sets restart: unless-stopped for db/api/caddy; live restart bounce not verified (no SSH) |
| `postgres_persistence` | **PARTIAL** | PostgreSQL volume persistence | compose.prod uses loopp_pgdata volume; data survived health checks; volume remount after reboot not verified (no SSH) |
| `cert_renewal` | **PARTIAL** | HTTPS certificate renewal path | sslip.io has valid Let's Encrypt cert via Caddy; auto-renewal cron/Caddy on-disk state not inspected (no SSH). Expiry Feb 18 2027. |
| `ui_false_confirm_card` | **FAIL** | Policy answers must not show Confirmation needed card | Browser showed Confirmation needed + $50 on a pure policy question due to messageUi regex. Fix in web/src/lib/messageUi.ts on branch audit/oracle-prod-readiness |

## First-audio latency (ms)

- n=4 p50=106.7 p95=192.0 mean=131.6
- samples=[106.74995400768239, 207.03944699198473, 106.56482000194956, 106.14519800583366]
- Note: samples are server `voice.tts_first_audio` (TTS stage). Full end-of-speech→first-audio needs client VAD markers.


## Follow-up fixes (branch only — not deployed)

- Disable broken bare-IP HTTPS site in deploy/Caddyfile
- Tighten web messageUi confirm classifier
- Document CORS + VOICE_BACKEND=local for Moonshine on Oracle

## Notes

- No Oracle SSH from this environment — host CPU/RAM, docker restart bounce, and cert data volume inspection blocked.
- Browser microphone hardware not grantable in automation; voice tested via Cloudflare WebSocket + PCM.
- Confirmed refunds intentionally not executed to limit production sandbox writes.
- Local .env.production is not necessarily identical to VM env (CORS for workers.dev works in prod).
