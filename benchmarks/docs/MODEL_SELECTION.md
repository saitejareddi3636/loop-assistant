# Production voice model selection

This note explains why Loopp’s local-first stack uses **Moonshine Tiny (STT)** and **Pocket TTS**, and how the isolated `benchmarks/` suite informed that choice. Numbers below refer to measured artifacts under `results/` after a real run on the reference host (`darwin-arm64` M2 / 8 GB). If those files are missing, regenerate with `python scripts/run_all.py` — do not invent figures.

## Decision summary

| Role | Production choice | Why |
|------|-------------------|-----|
| Local STT | Moonshine Tiny ONNX | Lowest RAM footprint that still works for short billing utterances on an 8 GB Mac; free/local (no per-minute ASR bill); acceptable invoice-ID recall on our synthetic set |
| Hosted STT fallback | Groq Whisper `large-v3-turbo` | Used when `VOICE_BACKEND=hosted` or local weights unavailable; pay-per-use, higher accuracy ceiling, no local GPU |
| Local TTS | Pocket TTS (`alba`) | Sub-0.5 s first-audio target on M2; streams chunks for barge-in; no cloud TTS fees |
| Not selected for prod STT | Moonshine Streaming Medium | Better capacity in principle, but heavier ONNX residency and not required once Tiny met the local RAM budget |
| Not selected for prod STT | Parakeet TDT 0.6B | Strong English ASR, but larger download/RSS and slower cold path on 8 GB hosts relative to Tiny |

## Cost trade-offs

| Option | Marginal cost | Notes |
|--------|---------------|-------|
| Moonshine Tiny + Pocket TTS | **$0 / minute** after one-time download | Fits the Phase 3 “local-first” demo on developer laptops; RAM is the scarce resource |
| Groq Whisper fallback | Groq ASR pricing (see current Groq rates) | Prefer for thin containers (`VOICE_BACKEND=hosted`) or when local RSS headroom is gone |
| Cloud TTS (not used) | Per-character / per-request | Avoided to keep the voice path offline-capable and predictable |
| Parakeet / Streaming Medium locally | $0 / minute | Cost is **memory and latency**, not invoices — both compete with LLM + Postgres on 8 GB |

For Loopp’s current scale (support-agent demo, not a multi-tenant call center), avoiding a second cloud speech vendor is worth more than squeezing another few WER points from a heavier local model.

## Accuracy trade-offs (measured on this host)

From `results/SUMMARY.md` (Darwin arm64 M2 / 8 GB, synthetic `say` fixtures, 2026-11-20 run):

| Model | Mean WER | Mean latency | Invoice hit-rate* | RSS after load |
|-------|----------|--------------|-------------------|----------------|
| Moonshine Tiny | 0.272 | 0.69 s | 100% | ~235 MB |
| Moonshine Streaming Medium | 0.241 | 0.22 s | 100% | ~429 MB |
| Parakeet TDT 0.6B (int8) | 0.252 | 0.61 s | 100% | ~756 MB |
| Pocket TTS | — | first-audio 0.11 s | — | ~516 MB |

\*Invoice hit-rate uses ASR-tolerant extraction (`INV-1042`, `INV1042`, `Invi 1042`, `envy 1042`, spaced `I N V`). Digits were recoverable for all three STT models on this set; orthography still differed.

Interpretation for production:

1. **WER** — Streaming Medium edged Tiny/Parakeet on this tiny synthetic set; differences are small and **not** a general ASR ranking.
2. **Invoice IDs** — All three recovered invoice digits after tolerant normalization. Tiny remains acceptable for Loopp tool routing on clear speech.
3. **Latency** — Streaming Medium was fastest offline; Tiny ~0.7 s warm is still compatible with utterance-final VAD. Pocket TTS cleared the &lt; 0.5 s first-audio target (mean 0.11 s).
4. **RSS** — Tiny stays lightest (~0.2 GB after load). Parakeet (~0.8 GB) plus Pocket (~0.5 GB) plus LLM pressure the 8 GB laptop budget; Tiny leaves more headroom with `VOICE_LAZY_LOAD`.

## Why not change production after this suite?

This suite is **diagnostic**. It may show Parakeet winning on WER; that alone does not justify swapping production adapters. Production stays on Moonshine Tiny + Pocket TTS unless a measured run shows Tiny failing invoice recall or exceeding the RAM budget while a lighter alternative exists. Any production change would land in `api/app/voice/` with its own review — never from editing these benchmark scripts.

## Limitations that affect interpretation

- Synthetic `say` audio understates real telephony noise, accents, and barge-in.
- One process, sequential loads → RSS is not a perfect A/B isolation.
- Ten utterances is enough to rank systems for Loopp’s billing vocabulary, not to publish a general ASR leaderboard.
- Hosted Groq Whisper is outside this suite (network + API key); compare using operational logs when needed.
