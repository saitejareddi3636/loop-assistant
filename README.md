# Loopp Support Agent — Phase 3

Customer-support agent with **Groq** tool-calling, **pgvector RAG**, **real-time voice**, and an **observability drawer**.

## Stack

- **Web:** React + TypeScript + Vite + Tailwind (chat, voice waveform, captions, observability)
- **API:** FastAPI + LangGraph + WebSocket voice
- **LLM:** Groq `openai/gpt-oss-120b` (`mock` retained for tests)
- **DB:** PostgreSQL + pgvector
- **Voice (local-first):** Moonshine ONNX STT · Pocket TTS · Silero VAD Lite  
  Hosted fallback: Groq Whisper STT · null TTS (browser can fill in)

## Phase status

| Phase | Status |
|-------|--------|
| 1 Chat + tools + Postgres | Working |
| 2 Groq + RAG + guardrails | Working |
| 3 Voice + observability + deploy prep | Working locally; **public cloud URL not live yet** |

## Quick start (Mac M2 8 GB)

```bash
cp .env.example .env
# Set GROQ_API_KEY and SESSION_SECRET

docker compose up -d db

cd api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-voice.txt   # local Moonshine/Pocket/Silero
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# new terminal
cd web && npm install && npm run dev
```

Open http://localhost:5173 — use **Start voice** (HTTPS or localhost required for mic).

## Voice benchmarks

**Comparative suite (WER / latency / RSS / invoice IDs / Pocket TTS):** isolated under [`benchmarks/`](benchmarks/) — does not modify production adapters. See [`benchmarks/README.md`](benchmarks/README.md) and measured [`benchmarks/results/SUMMARY.md`](benchmarks/results/SUMMARY.md).

**Smoke timing (production stack only):** from `api/benchmarks/voice_m2.json` (Darwin arm64):

| Metric | Measured |
|--------|----------|
| Silero VAD 100 frames | ~16 ms |
| Moonshine tiny warm mean | ~0.93 s / utterance |
| Pocket TTS first audio | ~0.16 s |
| Pocket TTS total (≈5 s audio) | ~1.5 s |
| RSS after STT+TTS | ~0.9 GB |

**Pass:** first-audio &lt; 0.5 s, RSS &lt; 2 GB.  
**Limitation:** warm STT ~1 s; cold Moonshine/Pocket loads are slower; concurrent TTS+STT+LLM on 8 GB needs lazy loading (enabled).

```bash
# Comparative suite
cd benchmarks && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python scripts/run_all.py

# Production smoke timing
cd api && source .venv/bin/activate && python scripts/benchmark_voice.py
```

## Tests

```bash
cd api && source .venv/bin/activate
PYTHONPATH=. pytest -q
```

## Deployment prep (not production-live yet)

- `Dockerfile` — API + built web
- `docker compose --profile full up --build` — db + api
- `.github/workflows/ci.yml` — API pytest + web build

**Public URL:** not deployed/tested in this phase. Next steps for a public demo:

1. Provision managed Postgres with pgvector (or Fly/Railway volume + compose)
2. Set `GROQ_API_KEY`, `SESSION_SECRET`, `VOICE_BACKEND=hosted` (or ship a larger RAM box for local voice)
3. Deploy the Docker image behind HTTPS (required for mic outside localhost)
4. Verify `/api/health`, chat turn, voice WebSocket, and interruption from a signed-out browser

Do not treat deployment as complete until that public URL is exercised.

## Architecture (Phase 3 additions)

```
api/app/voice/          STT/TTS/VAD adapters + WebSocket session
api/app/observability/  token/cost estimates + obs.metrics SSE events
api/app/security/       session HMAC tokens + sliding-window rate limits
web/src/components/     VoiceControls, Waveform, ObservabilityDrawer
```

Chat and voice share the same conversation rows and `run_agent_turn` / LangGraph path.
