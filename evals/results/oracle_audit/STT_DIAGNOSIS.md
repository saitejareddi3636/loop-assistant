# Oracle STT diagnosis: Groq Whisper vs Moonshine Tiny

**Date:** 2026-11-20  
**Constraint:** No blind switch; no Oracle resize/deploy from this branch.

## Live production observation

Spoken Cloudflare WebSocket E2E (`evals/scripts/oracle_voice_e2e.py`) against
`https://loopp-proxy.saitejareddi1503.workers.dev` reported:

| Field | Value |
|-------|-------|
| `voice.backend` | `stt=groq-whisper;tts=pocket-tts;vad=silero-vad-lite` |
| Pocket TTS | Working (binary TTS frames returned) |
| Moonshine Tiny | **Not** selected on the live stack |
| `/api/voice/diagnostics` | **HTTP 404** on current production (endpoint only on this review branch) |

Artifact: `evals/results/oracle_audit/spoken_e2e.json`.

## Why Whisper is active (code path)

`api/app/voice/factory.py` selection order when `VOICE_BACKEND=auto` (typical prod):

1. Try Moonshine Tiny ONNX.
2. On any load/import failure → log warning and fall through.
3. Use Groq Whisper as hosted STT.

Live backend string `stt=groq-whisper` with working `pocket-tts` means:

- **TTS/local torch path for Pocket is healthy** on the VM.
- **Moonshine did not become the active STT** — most likely failed import/weight load under the container RAM/CPU budget, or `VOICE_BACKEND`/`VOICE_STT` was set to prefer hosted.

Without SSH/`docker logs` (blocked in the readiness audit), the exact Moonshine exception is not readable from the public edge. The new `/api/voice/diagnostics` endpoint on this branch probes Moonshine vs Groq vs Pocket in-process and returns the failure traceback tail so operators can confirm without guessing.

## Local verification (this laptop)

```
active stt=moonshine-onnx-tiny;tts=pocket-tts;vad=silero-vad-lite
moonshine_ok moonshine-onnx-tiny
```

So Moonshine Tiny **is** the reliable local backend on the M2/dev host. Production Oracle currently **reliably** serves Whisper + Pocket.

## Production configuration recommendation (do not auto-apply)

| Host | Reliable STT today | Action |
|------|--------------------|--------|
| Dev / M2 | Moonshine Tiny | Keep `VOICE_BACKEND=local` / `auto` |
| Oracle prod (current) | **Groq Whisper** | Keep Whisper until diagnostics prove Moonshine loads; then set `VOICE_BACKEND=local` only after a successful `/api/voice/diagnostics` probe |

**Do not** switch Oracle to Moonshine blindly. Deploy diagnostics first, read `attempts[].error`, fix load errors (weights, onnxruntime, RSS), then flip.

## Related spoken-path note

Whisper often emits `INV1042` (no hyphen). This branch normalizes compact IDs to `INV-1042` before the agent turn (`normalize_transcript_ids`) so tool lookup matches fixtures.
