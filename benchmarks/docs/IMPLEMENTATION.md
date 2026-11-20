# Benchmark implementation notes

## Isolation from production

- All runners live under `benchmarks/` and install into `benchmarks/.venv`.
- No imports from `api.app.voice.*`. Production adapters stay untouched.
- `.gitignore` excludes `.cache/`, `.venv/`, generated `fixtures/audio/`, `results/raw_audio/`, and weight extensions (`*.onnx`, `*.pt`, …).

## STT backends

| ID | Loader | Notes |
|----|--------|-------|
| `moonshine_tiny` | `useful-moonshine-onnx` `transcribe(path, "moonshine/tiny")` | Same family as production |
| `moonshine_streaming_medium` | ONNX Runtime on Immortalizer merged-decoder INT8 + HF tokenizer | Offline greedy decode; config from UsefulSensors card |
| `parakeet_0_6b` | `onnx-asr` `nemo-parakeet-tdt-0.6b-v2` (int8 preferred) | Larger English ASR baseline |

## Metrics

- **WER:** `jiwer` on lightly normalized text (casefold, strip punctuation).
- **Invoice recall:** regex + spoken digit expansion in `metrics.py`.
- **Latency:** `time.perf_counter` around `transcribe` / TTS generate.
- **CPU / RSS:** `psutil` sampling thread while inference runs.

## Charts & summary

`plot_results.py` writes PNGs under `results/charts/`. `write_summary.py` builds `results/SUMMARY.md` strictly from JSON — if JSON is absent, it exits rather than inventing a table.

## Known limitations

1. Fixture speech is TTS-generated, so absolute WER is optimistic vs. real callers.
2. Streaming Medium’s streaming-chunk latency is not measured; only full-utterance WER/latency.
3. Parakeet first download is large; subsequent runs hit `benchmarks/.cache/`.
4. Pocket TTS depends on PyTorch; cold start dominates the first load measurement.
5. Running STT models back-to-back can leave allocator fragmentation; interpret RSS deltas with that in mind.
