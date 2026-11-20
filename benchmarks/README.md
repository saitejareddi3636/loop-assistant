# Loopp voice benchmarking suite

Isolated STT/TTS evaluation for Loopp. Lives under `benchmarks/` and does **not** import or modify `api/app` production voice adapters.

## What we measure

| Area | Models | Metrics |
|------|--------|---------|
| STT | Moonshine Tiny, Moonshine Streaming Medium (INT8 ONNX), NVIDIA Parakeet TDT 0.6B V2 | WER, latency, CPU%, RSS, invoice-ID hit-rate |
| TTS | Pocket TTS (`alba`) | First-audio latency, total synth time, RTF, RSS |

## Quick start

```bash
cd benchmarks
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Full suite (fixtures → STT → TTS → charts → SUMMARY.md)
python scripts/run_all.py
```

Partial runs:

```bash
python scripts/generate_fixtures.py
python scripts/run_stt_benchmark.py --models moonshine_tiny
python scripts/run_tts_benchmark.py
python scripts/plot_results.py
python scripts/write_summary.py
```

## Layout

```
benchmarks/
  configs/benchmark.yaml          # model list + run counts
  fixtures/manifests/             # ground-truth transcripts (committed)
  fixtures/audio/                 # generated WAVs (gitignored)
  scripts/                        # runners + metrics
  results/                        # JSON/CSV/SUMMARY + charts (committed after a real run)
  .cache/                         # HF / ONNX weight cache (gitignored)
  .venv/                          # local env (gitignored)
```

## Reproducibility notes

- Config seed / warmups / timed runs: `configs/benchmark.yaml`.
- Fixtures are synthesized with macOS `say` (or `espeak-ng`) at 16 kHz mono PCM16. They are **not** real caller audio.
- Model weights download into `benchmarks/.cache/` and are excluded from Git (along with `*.onnx`, `*.wav`, secrets).
- Results JSON/CSV and charts under `results/` are written only after a measured run — do not invent numbers.

## Production selection

See [docs/MODEL_SELECTION.md](docs/MODEL_SELECTION.md) for why production uses **Moonshine Tiny + Pocket TTS** (with Groq Whisper as hosted fallback), including cost and accuracy trade-offs against the models measured here.

## Implementation notes

- STT backends are self-contained in `scripts/stt_backends.py` so Parakeet / Streaming Medium never enter the production factory.
- Invoice recall accepts `INV-1042`, `inv 1042`, and spoken digit forms (`one zero four two`) via `scripts/metrics.py`.
- Streaming Medium is scored with an **offline full-utterance** decode of the merged-decoder INT8 export; chunked streaming latency is out of scope for this suite.
- Resource samples use `psutil` in a background thread (~50 ms). Sequential model loads in one process mean RSS is indicative of peak residency, not a clean isolated cgroup.

## Related (production smoke timing)

The app still has a lightweight latency smoke script at `api/scripts/benchmark_voice.py` writing `api/benchmarks/voice_m2.json`. That path does **not** compute WER or compare Parakeet / Streaming Medium — use this suite for those comparisons.
