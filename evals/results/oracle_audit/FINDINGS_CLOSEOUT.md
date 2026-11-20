# Prod audit findings — close-out (`fix/prod-audit-findings`)

**Branch:** `fix/prod-audit-findings` (review only — not deployed)  
**Date:** 2026-11-20

## Checklist

| # | Finding | Status |
|---|---------|--------|
| 1 | False refund confirmation card | **Fixed** — `meta.ui.confirmation` only when `issue_mock_refund` returns `confirmation_required`; frontend uses `assistantUiFromMeta` (no reply regex) |
| 2 | Assistant Markdown | **Fixed** — `MarkdownText` + `react-markdown` in MessageList (final + streaming) |
| 3 | TTS ID/currency pronunciation | **Fixed** — `normalize_for_speech` in Pocket TTS path |
| 4 | Whisper vs Moonshine | **Diagnosed** — see `STT_DIAGNOSIS.md`; live prod is Whisper+Pocket; do not switch blindly |
| 5 | Spoken CF → STT → agent → TTS | **PASS** — `spoken_e2e.json` |
| 6 | True EOS → first audio | **Measured** — client wall-clock **~3995 ms** (network+STT+agent+TTS); server `eos_to_first_audio_ms` awaits deploy |
| 7 | Browser mic / interrupts | **Documented** — `MIC_INTERRUPT_LIMITS.md` (automation BLOCKED) |
| 8 | PR #1 / #2 overlap | **Documented** — `PR_OVERLAP.md`; this branch supersedes PR #2 regex UI |
| 9 | Regressions | See below |

## Spoken E2E (live production, no deploy)

| Metric | Value |
|--------|-------|
| STT | `groq-whisper` |
| TTS | `pocket-tts` (533760 bytes this run) |
| Transcript | includes `INV1042` / invoice (hyphen normalize not on prod yet) |
| Assistant | asks to confirm $29 refund on INV-1042 + PRO-BILL-3.2 |
| Tools | SSE tool.started/completed/failed present |
| `client_eos_to_first_audio_ms` | **3995** |
| `server_eos_to_first_audio_ms` | null (endpoint/metric not deployed) |
| `/api/voice/diagnostics` | 404 until this branch is deployed |

## Regressions (this machine)

| Suite | Result |
|-------|--------|
| `api` pytest (LLM_PROVIDER=mock) | **19 passed** |
| `evals` deterministic | **22/22 expected after scenario update** (refund turn-1 now expects `confirmed=false`) |
| Live Groq suite | Not re-run (prior 429 preserved; no Oracle change) |

## Remaining gaps (not failures of this branch)

1. Deploy required for diagnostics, server EOS metric, transcript ID hyphen normalize, Markdown/structured UI on production.
2. Manual browser mic + acoustic barge-in still human-only.
3. Oracle Moonshine load cause still needs SSH or deployed diagnostics before any STT switch.
4. Merge order: PR #1 → rebase PR #2 → land this branch’s structured UI over PR #2 regex.
