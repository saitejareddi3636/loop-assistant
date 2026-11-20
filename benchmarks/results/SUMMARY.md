# Loopp voice benchmark summary

Evidence-only report generated from measured JSON artifacts.

## Host

- Label: `darwin-arm64-m2-8gb`
- System: Darwin 25.2.0 (arm64)
- RAM: 8.0 GB · CPUs: 8
- Python: 3.13.3
- Timestamp (UTC): 2026-11-20T19:31:54.239117+00:00

## STT comparison

| Model | Mean WER | Mean latency (s) | Invoice ID hit-rate | RSS after load (MB) | Load (s) |
|---|---:|---:|---:|---:|---:|
| Moonshine Tiny (ONNX) | 0.2717 | 0.685 | 100.0% | 235 | 1.87 |
| Moonshine Streaming Medium (ONNX INT8) | 0.2408 | 0.218 | 100.0% | 429 | 1.16 |
| NVIDIA Parakeet TDT 0.6B V2 (ONNX) | 0.2519 | 0.610 | 100.0% | 756 | 23.83 |

### Per-utterance WER (last timed hypothesis)

| Utterance | moonshine_tiny | moonshine_streaming_medium | parakeet_0_6b |
|---|---:|---:|---:|
| `inv_1042_clear` | 0.286 | 0.286 | 0.286 |
| `inv_1042_spoken` | 0.545 | 0.636 | 0.636 |
| `inv_1038_refund` | 0.444 | 0.444 | 0.556 |
| `tier_pro` | 0.200 | 0.000 | 0.000 |
| `confirm_refund` | 0.286 | 0.286 | 0.286 |
| `policy_ask` | 0.200 | 0.000 | 0.000 |
| `inv_2001_foreign` | 0.200 | 0.200 | 0.200 |
| `short_ack` | 0.000 | 0.000 | 0.000 |
| `amount_and_invoice` | 0.556 | 0.556 | 0.556 |
| `beckett_control` | 0.000 | 0.000 | 0.000 |

## Pocket TTS

- Voice: `alba` · sample rate: 24000 Hz · load: 1.48s
- Mean first-audio: **0.111s** · mean total: 1.524s
- Pass first-audio < 0.5s: `True` · RSS after load: 516 MB

| Utterance | First audio (s) | Total (s) | Audio duration (s) | RTF |
|---|---:|---:|---:|---:|
| 0: Your Pro refund for invoice INV-1042 is ready fo… | 0.070 | 1.755 | 4.77 | 0.37 |
| 1: I can process a twenty-nine dollar refund after … | 0.176 | 2.113 | 3.63 | 0.58 |
| 2: Your account is on the Pro tier. | 0.086 | 0.702 | 1.89 | 0.37 |

## Charts

- `charts/stt_comparison.png` — WER, latency, invoice hit-rate
- `charts/stt_rss.png` — RSS after load
- `charts/tts_pocket.png` — Pocket TTS first-audio vs total

## Limitations (apply to these numbers)

- Fixtures are **synthetic** (`say` / `espeak`), not production caller audio.
- STT models were evaluated **sequentially** in one process; RSS deltas are indicative, not a clean multi-process isolation.
- Moonshine Streaming Medium used an **offline full-utterance** path (not chunked streaming latency).
- Invoice hit-rate rewards any accepted orthography of `INV-####`; spoken letter/digit forms are normalized in `metrics.py`.

