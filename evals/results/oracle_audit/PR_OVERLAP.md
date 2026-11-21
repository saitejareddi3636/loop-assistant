# PR #1 / #2 / #3 merge status

| PR | Branch | Intent | Status |
|----|--------|--------|--------|
| [#1](https://github.com/saitejareddi3636/loop-assistant/pull/1) | `feat/evals-regression-framework` | Isolated `evals/` regression harness | **MERGED** into `main` |
| [#2](https://github.com/saitejareddi3636/loop-assistant/pull/2) | `audit/oracle-prod-readiness` | Oracle audit + Caddy bare-IP disable + regex confirm tweak | Open — **do not merge regex UI**; useful bits already on #3 |
| [#3](https://github.com/saitejareddi3636/loop-assistant/pull/3) | `fix/prod-audit-findings` | Structured confirm UI, Markdown, TTS, STT diagnosis | Rebased onto `main` after #1 |

## Preserved from PR #2 (on #3 / this branch)

- `deploy/Caddyfile` — bare-IP HTTPS disabled (kept)
- `evals/results/oracle_audit/REPORT.md` + `report.json` — audit evidence (kept)
- README Oracle/Cloudflare pointers (kept / updated via audit commit)

## Explicitly **not** reintroduced from PR #2

- Regex / tightened-regex `classifyAssistantMessage` confirmation card logic  
  → replaced by structured `message.meta.ui` + `assistantUiFromMeta` only

## Recommended remaining actions

1. Land **PR #3** after review (already contains structured UI + TTS/STT hardening).
2. Close **PR #2** as superseded once #3 merges (or leave open only for historical audit discussion).
