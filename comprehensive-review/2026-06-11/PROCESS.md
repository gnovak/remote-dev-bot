# Comprehensive review (2026-06-11) — process record

How this review was produced — archived alongside the findings as
documentation of method, in case it's useful as a template for future passes.

Started 2026-06-11 against dev @ de72856 (PRs #631-#633 just merged).
Goal: review all code on dev, note bugs + stale comments/docs, analyze
real-world usage (rdb self-dev + bridge-analysis), recommend prompting
adjustments, propose future directions.

Method: sequential subagents writing incremental findings to disk (per the
"Fable budget protocol" memory entry — multi-hour reviews need to survive
API blocks / usage limits, so subagents append after each unit reviewed
rather than batching at the end). Subagent prompts are in `AGENT-PROMPTS.md`.

## Phases

- [x] 0. Workspace + dev branch sync
- [x] 1. Code review: lib/*.py (+ tests/ skim)            → `findings-code.md` (11 BUG / 8 DRIFT / 12 SMELL / 10 STALE / 19 NIT; headline: CWE handler unreachable resolve.py:1523)
- [x] 2. Workflows + config review (.github/, yaml, e2e.sh) → `findings-workflows.md` (~18 BUG / 11 DRIFT / 10 STALE / 13 SMELL; headline: design-job heredoc 5-tuple unpack of `maybe_distill` → distillation silently broken in `/agent-design`; `test.yml` never runs on PRs to dev)
- [x] 3. Documentation staleness review (all *.md)        → `findings-docs.md` (7 WRONG / ~21 STALE / 9 GAP / 6 NIT; headline: `install.md` curls deleted `remote-dev-bot.yaml.template` → fresh installs 404; README cites nonexistent `SECURITY_GATE`)
- [x] 4. Real-world usage analysis (gh: rdb + bridge-analysis) → `findings-usage.md` (31 invocations May 5-29, 14 deep-dives; cache savings now 3-5× paid spend; premature victory = stopping-criterion problem, 44/150 iters on stub; council caught BT shortcut but nothing acts on findings; zero runs after May 31 → #631-633 unvalidated)
- [x] 5. Prompt analysis (main session, had history context) → `findings-prompts.md` (era 1→2 prompt swing; council-loop closure as highest-leverage; model-agnosticism intact but prompt length growing)
- [x] 6. Synthesis → `SUMMARY.md` (Opus 4.7 after Fable was blocked mid-write by a usage-policy false positive on the security-vulnerability content; security findings phrased clinically on the re-write)

## Notes for next time

- Phase 4 (gh API usage analysis) was the cheapest and produced the most
  novel insight per dollar. Worth running first next time, not last.
- Synthesizing all security findings into one document tripped Anthropic's
  usage-policy classifier on Fable 5 — Opus 4.7 in a fresh-context window
  did the same synthesis fine. Future reviews: lean toward a model with
  more context headroom for the synthesis stage, or split the security
  section into a separate file.
- All 5 findings files survived the mid-stream API block exactly because
  the protocol mandated incremental disk writes. The protocol works.
