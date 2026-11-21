# Browser microphone & interruption — what automation cannot verify

## Automated coverage (present)

| Check | How | Limit |
|-------|-----|-------|
| Voice WebSocket PCM → STT → agent → TTS | `oracle_voice_e2e.py`, evals voice scenarios | Uses synthetic/`say` WAV, not `getUserMedia` |
| Barge-in generation bump | `voice_barge_in_interrupt` eval + session `generation` cancel | Simulates new speech frames while speaking; not a real mic overlap |
| Concurrent WS sessions | Oracle audit script | Server-side only |

## Manual-only (cannot fully automate in CI / headless)

1. **Browser microphone permission** — Chrome/Safari permission prompts, HTTPS secure-context, and device selection require a human. Headless Cursor browser automation cannot grant mic or drive real `MediaStream` capture for this app.
2. **Acoustic barge-in** — Real overlap of user speech with Pocket TTS playback (echo cancellation, half-duplex UX) needs a physical mic and speakers.
3. **Push-to-talk / hold-to-talk UX** — If the UI uses pointer events + mic stream, Playwright can click but still cannot supply live audio without injected fake devices.
4. **Network jitter under real mic** — Chunked 20 ms frames from a laptop over cellular vs the scripted sleep(0.02) stream differ.

## Manual checklist (reviewer)

- [ ] Open production UI over HTTPS; allow microphone when prompted.
- [ ] Speak: “I was charged twice on invoice INV-1042 for twenty nine dollars.”
- [ ] Confirm transcript shows `INV-1042` (or hyphen-normalized equivalent after deploy).
- [ ] While agent is speaking, interrupt mid-sentence; confirm audio stops / new turn starts (`voice.ignored` or new transcript).
- [ ] Deny mic permission once; confirm UI shows a clear error (no silent hang).

## Status for this audit branch

Automated spoken CF path: **PASS** (transcript + assistant + TTS audio + client EOS wall-clock).  
Manual mic/interrupt: **BLOCKED / documented** — left for human QA; not claimed as verified by automation.
