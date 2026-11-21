# Oracle STT diagnosis: Groq Whisper vs Moonshine Tiny

**Date:** 2026-11-20 (updated)  
**Constraint:** No blind switch; no Oracle resize/deploy from this branch; no silent hosted fallback.

## Live production observation

Spoken Cloudflare WebSocket E2E against
`https://loopp-proxy.saitejareddi1503.workers.dev` reported:

| Field | Value |
|-------|-------|
| `voice.backend` | `stt=groq-whisper;tts=pocket-tts;vad=silero-vad-lite` |
| Pocket TTS | Working |
| Moonshine Tiny | **Not** selected on the live stack |
| `/api/voice/diagnostics` | **HTTP 404** on current production (endpoint on review branch only) |
| SSH `ubuntu@` / `opc@` `129.80.125.203` | **Permission denied (publickey)** |

Artifact: `evals/results/oracle_audit/spoken_e2e.json`.

## Root cause (confirmed)

### 1. Persistent env: `VOICE_STT=groq` (primary)

Oracle runtime had:

| Var | Value |
|-----|-------|
| `VOICE_BACKEND` | `auto` |
| `VOICE_STT` | **`groq`** |

`VOICE_STT=groq` forces hosted Whisper in `factory.py` and **skips** Moonshine even when
`MoonshineSTTAdapter()` initializes successfully (`moonshine-onnx-tiny` confirmed in-container).

**Fix:** pin `VOICE_BACKEND=local` and `VOICE_STT=local` in `docker-compose.prod.yml`
`api.environment` (overrides `.env.production`), Dockerfile defaults, and `.env.production`.
See `STT_CONFIG_FIX.md`.

### 2. Silent hosted fallback (secondary, already removed)

Prior `factory.py` with `VOICE_BACKEND=auto` could also fall through to Whisper after a Moonshine
load error. That path is **removed** — local/auto fail closed; Whisper only when hosted is explicit.

### 2. Config surfaces to inspect on the VM (needs SSH)

| Item | Expected for Moonshine | Where |
|------|------------------------|-------|
| `VOICE_BACKEND` | `local` or `auto` | `.env.production` / container env |
| `VOICE_STT` | `auto` or `local` (not `groq`) | same |
| Image packages | `useful-moonshine-onnx`, `onnxruntime` | `Dockerfile` installs `requirements-voice.txt` |
| Weights | Moonshine tiny ONNX downloaded on first use | container FS / HF cache |
| API logs | `Moonshine STT failed…` then previously `Voice stack ready: stt=groq-whisper` | `docker logs loopp-api` |

Local docker-compose (`VOICE_BACKEND:-hosted`) is a **dev** default and is **not** what `docker-compose.prod.yml` uses (prod uses `env_file: .env.production`).

### 3. Local laptop verification

```
active stt=moonshine-onnx-tiny;tts=pocket-tts;vad=silero-vad-lite
```

Moonshine Tiny works on the M2/dev host. Oracle live currently serves Whisper because of (1).

## Blocked: measure Moonshine latency/accuracy **on Oracle**

SSH is denied (`publickey`) for `ubuntu` and `opc`. Cannot read:

- `docker logs loopp-api | grep -i moonshine`
- container `printenv VOICE_BACKEND VOICE_STT`
- `python -c "from app.voice.moonshine_stt import MoonshineSTTAdapter; …"` inside the api container
- RSS / onnxruntime errors during weight download

### Exact access needed (next action for humans)

1. SSH key authorized for the Oracle VM user that owns the compose stack (`ubuntu` or `opc`), **or** console access in OCI.
2. From the VM:
   ```bash
   docker exec loopp-api printenv VOICE_BACKEND VOICE_STT
   docker logs loopp-api 2>&1 | grep -iE 'moonshine|voice stack|whisper' | tail -50
   docker exec loopp-api python -c "from app.voice.moonshine_stt import MoonshineSTTAdapter; print(MoonshineSTTAdapter().name)"
   ```
3. After deploying this branch’s `/api/voice/diagnostics`, curl it through Cloudflare and read `attempts` / `recommendation`.
4. Only then set `VOICE_BACKEND=local` (or keep `auto`) once Moonshine probe `ok=true`. If Moonshine cannot load, set `VOICE_BACKEND=hosted` **explicitly** — never rely on silent fallback.

## Production configuration recommendation (do not auto-apply)

| Host | Reliable STT today | Action |
|------|--------------------|--------|
| Dev / M2 | Moonshine Tiny | `VOICE_BACKEND=local` / `auto` |
| Oracle prod (current live) | Groq Whisper via silent fallback | Deploy fail-closed factory + diagnostics; SSH to capture Moonshine error; fix weights/deps **or** set `VOICE_BACKEND=hosted` deliberately |
