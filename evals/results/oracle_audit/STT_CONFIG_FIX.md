# Oracle STT config fix — VOICE_STT=groq → local

## Where Oracle Docker env vars are configured

| Layer | Path | Role |
|-------|------|------|
| **Primary (VM)** | `.env.production` on the Oracle host, loaded by `docker-compose.prod.yml` → `api.env_file` | Persistent runtime secrets + voice knobs |
| **Compose override** | `docker-compose.prod.yml` → `api.environment` | **Pins** `VOICE_BACKEND` / `VOICE_STT` (overrides env_file) |
| **Image defaults** | `Dockerfile` `ENV` | Defaults if neither file sets the var |
| **Not used on Oracle** | root `docker-compose.yml` (`VOICE_BACKEND:-hosted`) | Local Mac “full” profile only |

## Confirmed misconfiguration

| Var | Was (Oracle) | Effect |
|-----|--------------|--------|
| `VOICE_BACKEND` | `auto` | Would prefer Moonshine |
| `VOICE_STT` | **`groq`** | **Forces Groq Whisper** in `factory._want_hosted_stt` / skips local STT |

`MoonshineSTTAdapter()` already initializes successfully in the production container (`moonshine-onnx-tiny`). Whisper was selected by **config**, not by a Moonshine load failure.

## Persistent fix (this branch)

1. `docker-compose.prod.yml` sets `VOICE_BACKEND: local` and `VOICE_STT: local` under `api.environment`.
2. `Dockerfile` image defaults set the same.
3. `.env.example` and local `.env.production` (gitignored) set `local` / `local`.
4. Factory still **does not** silently fall back to Whisper.

## Deploy (requires SSH — blocked from this agent)

```bash
# on Oracle host, in the loop-ai / loop-assistant repo
git fetch origin && git checkout fix/prod-audit-findings && git pull
# ensure .env.production has:
#   VOICE_BACKEND=local
#   VOICE_STT=local
docker compose -f docker-compose.prod.yml up -d --build api
docker exec loopp-api printenv VOICE_BACKEND VOICE_STT
# expect: local / local
```

Then verify via CF Worker voice WebSocket that `voice.backend` is
`stt=moonshine-onnx-tiny;tts=pocket-tts;…`.
