# PR #1 vs PR #2 overlap

| PR | Branch | Intent |
|----|--------|--------|
| [#1](https://github.com/saitejareddi3636/loop-assistant/pull/1) | `feat/evals-regression-framework` | Isolated `evals/` regression harness + mock LLM Basic-tier fix |
| [#2](https://github.com/saitejareddi3636/loop-assistant/pull/2) | `audit/oracle-prod-readiness` | Oracle audit report + Caddy bare-IP disable + regex confirm UI tweak + **almost all of PR #1 files** |

## Conflict risk

PR #2 was branched in a way that **already contains the evals tree from PR #1**. Merging both into `main` without rebasing will create large overlapping diffs on `evals/**`, `README.md`, `api/app/agent/mock_llm.py`, and CI.

## Recommended merge order (no auto-deploy)

1. Merge **PR #1** first (evals framework).
2. Rebase **PR #2** onto updated `main` and drop duplicated evals commits so it only keeps audit-specific deltas (`deploy/Caddyfile`, oracle audit reports, temporary UI tweak).
3. Land product fixes from **`fix/prod-audit-findings`** (this branch) after or instead of the temporary regex tweak in PR #2 — structured `meta.ui` replaces the regex confirm card.

Do **not** merge PR #2’s regex `messageUi` change if this branch’s structured confirmation is merging in the same window.
