Failed scenario artifacts land in `_runs/<scenario_id>/` (gitignored).

Each failure keeps `failure.json` (trace, assertions, timings) and `debug_suggestion.json`.
Voice runs may also store generated TTS wavs for reproduction.
