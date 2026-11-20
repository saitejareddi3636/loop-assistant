# Loopp regression evals

End-to-end AI regression tests for the **existing** Loopp pipeline:

`Voice → Silero VAD → Moonshine Tiny STT → LangGraph → Groq/Mock LLM → PostgreSQL/pgvector RAG + Tools → Pocket TTS`

This suite lives in `evals/` and is separate from `benchmarks/` (speech-model comparison only).

## Isolation rules

- Uses a **separate** Postgres database `loopp_evals` (port **5434** by default).
- Financial tools already use **mock refunds** (`issue_mock_refund`) — no real money movement.
- Does **not** restart Oracle, touch production data, or change production model defaults.
- Never point `DATABASE_URL` at the production DB (`loopp` on 5433 / Oracle).

## Quick start (deterministic / CI)

```bash
# 1) Isolated DB
cd evals
docker compose up -d
cp -n .env.example .env

# 2) Python deps (reuse api venv)
cd ../api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-voice.txt
pip install -r ../evals/requirements.txt

# 3) Run deterministic suite (mock LLM + tools + barge-in sim)
cd ../evals
PYTHONPATH=../api:. python scripts/run_evals.py --suite deterministic
```

Report: `evals/results/latest/SUMMARY.md`  
Failures: `evals/failures/_runs/<scenario_id>/`

## Suites

| Suite | Command | What runs |
|-------|---------|-----------|
| `deterministic` | `python scripts/run_evals.py --suite deterministic` | Direct tools, mock LangGraph agent, voice barge-in sim (CI) |
| `live` | `python scripts/run_evals.py --suite live` | Real Groq LLM + tools + RAG (manual; needs `GROQ_API_KEY`) |
| `voice` | `python scripts/run_evals.py --suite voice` | Real STT + LangGraph + TTS audio (manual; heavy) |
| `all` | `python scripts/run_evals.py --suite all` | Everything available |

Single scenario:

```bash
PYTHONPATH=../api:. python scripts/run_evals.py --suite deterministic --only agent_refund_confirm_flow
```

## Scenario kinds

- `tools` — deterministic tool/domain assertions (no LLM)
- `agent_mock` — full `run_agent_turn` with `LLM_PROVIDER=mock`
- `agent_live` — full agent with real Groq
- `voice_live` — production STT/TTS adapters + agent (audio under `fixtures/audio/`, gitignored)
- `voice_sim` — barge-in interrupt without loading speech weights

Deterministic assertions cover refund confirmation, tool args, idempotency, and scope. An optional AI judge runs on live/voice only and **cannot** override safety tool assertions.

## Debugging failures

1. Open `failures/_runs/<id>/failure.json` and `debug_suggestion.json`
2. Fix on a development branch under `api/app/` if production behavior is wrong
3. Rerun the failed scenario, then the full deterministic suite
4. **Do not** loosen golden expectations just to force a pass, auto-deploy, or hide failures

```bash
PYTHONPATH=../api:. python scripts/debug_failure.py agent_refund_confirm_flow
```

## Measured results (2026-11-20)

| Suite | Result |
|-------|--------|
| Deterministic | **22/22 PASS** (re-verified at milestone close) |
| API pytest | **14/14 PASS** |
| Live continuous | **2/5 PASS** — remaining failures are **Groq 429 TPM** |
| Live after cooldown | **3/3 PASS** on previously failed ids |
| Voice subset | **3/3 PASS** (real STT + LLM + TTS) |

See [`results/VERIFICATION.md`](results/VERIFICATION.md) and preserved rate-limit artifacts under [`results/preserved_failures/`](results/preserved_failures/).

## Limitations

- Continuous `--suite live` on Groq free/on_demand (**~8000 TPM**) is **rate-limited**; do not use uninterrupted live green as a merge gate.
- Audio fixtures are synthetic (`say` / generated), not telephony.
- Harness calls production adapters without a browser WebSocket client.

## Oracle production audit

Measured live against Cloudflare + Oracle origin (no auto-deploy):

```bash
PYTHONPATH=../api:. python scripts/oracle_prod_audit.py
```

Report: [`results/oracle_audit/REPORT.md`](results/oracle_audit/REPORT.md).

## GitHub Actions

Deterministic evals run in CI (see `.github/workflows/ci.yml` job `test-evals`). Live/voice suites are manual only.
