# Real-world usage analysis: remote-dev-bot, May–June 2026

Sources: `gh api` on issue/PR comments of gnovak/remote-dev-bot and gnovak/bridge-analysis
(all comments since 2026-05-01, fetched 2026-06-XX). Read-only on GitHub.

## Inventory

**gnovak/remote-dev-bot (self-dev via /dogfood-\*):** essentially ZERO dogfood usage in
May–June. All 20 May PRs (#612–#633) were authored directly by gnovak (local Claude Code
sessions), not by the bot. Only trace: issue #599 "Rdb appears broken" (updated May 17).
Dogfood-driven self-dev was an April phenomenon; in May the repo's own development moved
off the bot. All real-world usage signal comes from bridge-analysis.

**gnovak/bridge-analysis (real consumer):** 31 invocations May 5 – May 29. Verb spelled
`/agent resolve` (space form) for most; `/agent-delegate` / `/agent-review` (hyphen) late
May. Model: `claude-small` = anthropic/claude-sonnet-4-6 for every run. **No runs at all
after May 29** — issue #441 (created Jun 11) has zero comments. So the May-31 prompt fixes
(rdb #631–633) have NO production runs after them; only #628 (May 27) saw subsequent use
(May 27–29).

| Date | Issue | Verb | Outcome |
|---|---|---|---|
| 05-05 | #355 | resolve | PR #359 MERGED |
| 05-15 | #364 | resolve | 1st attempt → no PR (cost comment only); re-invoked 01:31 same day → PR #371 MERGED |
| 05-15 | #365 | resolve | PR #366 MERGED |
| 05-15 | #367 | resolve | PR #369 MERGED |
| 05-15 | #368 | resolve | PR #370 MERGED |
| 05-17 | #374 | resolve | PR #378 MERGED |
| 05-17 | #375 | resolve | PR #377 MERGED |
| 05-18 | #384 | resolve | PR #389 MERGED |
| 05-18 | #383 | resolve | PR #391 MERGED |
| 05-19 | #393 | workshop | apparent failure (two bare Model/cost comments, no Stage 1 output); re-run next day |
| 05-20 | #394 | resolve | PR #397 MERGED |
| 05-20 | #395 | resolve | PR #398 MERGED |
| 05-20 | #392 | resolve | PR #399 MERGED |
| 05-20 | #393 | workshop | Stage 1 + Stage 2 council complete |
| 05-21 | #405 | resolve | PR #406 MERGED |
| 05-21 | #393 | design | design comment posted |
| 05-21 | #407 | resolve | PR #410 MERGED |
| 05-22 | #415 | workshop | complete |
| 05-22 | #415 | design ×2 | design comments posted (iterative refinement w/ human feedback) |
| 05-23 | #415 | resolve | PR #417 MERGED |
| 05-23 | #393 | resolve | PR #418 MERGED |
| 05-26 | #436 | delegate | full 6-stage pipeline → PR #437 MERGED (the known premature-victory stub) |
| 05-27 | #436 | resolve | PR #438 OPEN (post-#628-fix run) |
| 05-27 | #438 | review ×2 | solo review + council review posted |
| 05-29 | #439 | workshop | complete |
| 05-29 | #440 | workshop | complete |
| 05-29 | #439 | design | design posted (post-#628) |
| 05-29 | #440 | design | design posted (post-#628) |

Verb mix: resolve 17, workshop 5, design 6, delegate 1, review 2.
Resolve success rate: 16/17 invocations produced a merged-or-open PR (one May-15 retry).
All agent resolve PRs eventually merged except #438 (open, the web-app frontend).

## Run: bridge-analysis#355 resolve 2026-05-05 (earliest May run, pre-cache-fix)
- → PR #359 MERGED. Cost $0.49, 10 iters, 3m11s, 330K in / 15K out, 1021 LOC (new notebook), 2.1k LOC/$, 162.4 Kbit/$.
- Status log: cache line present but small — "282K tokens read from cache, ~$0.36 saved". No distillation line (feature not shipped yet).
- Cleanest run in the corpus: 10 iterations, huge single-file output. No thrash.

## Run: bridge-analysis#364 resolve 2026-05-15 (FAILURE + retry)
- 1st attempt: crashed at iter 1 — `litellm.InternalServerError: AnthropicError … "overloaded_error"`. Failure comment: "⚠️ Agent could not fully resolve this issue", cost table shows Time 4m47s, 1 iter, 0 tokens, $0.00. Infra/provider failure, not agent behavior.
- Retry 1h later → PR #371 MERGED: $0.35, 13 iters, 1m48s, 425K in / 5.2K out, 294 LOC.
- Only hard failure among the 17 resolve invocations.

## Run: bridge-analysis#365 resolve 2026-05-15
- → PR #366 MERGED. $0.51, 32 iters, 3m54s, 789K in / 9.9K out, 559 LOC, 1.1k LOC/$.
- Cache: 755K read, ~$0.43 saved. No distillation line.
- Status log shows iters 20–25 "creating the notebook… [Changes: (none) [+dirty]]" — file built via uncommitted edits, mild re-reading churn but completed fine.

## Run: bridge-analysis#375 resolve 2026-05-17 (first runs w/ distillation + restored cache)
- → PR #377 MERGED. $1.11, 18 iters, 3m58s, 1.4M in / 15K out, 816 LOC.
- Distillation line appears: "5.5K → 1.5K tokens (~$0.03 saved)" — trivial savings on small issue threads.
- Cache: 1.2M read, ~$3.29 saved — cache savings now ~3x the run cost (formula fixed by rdb #621, May 15).
- Sister run #374 → PR #378: $1.29, 18 iters, 1.5M in, cache $3.67 saved. Note: per-run COST roughly doubled vs May-15 runs ($0.35–0.57 → $1.11–1.29) as input tokens tripled; cache absorbed most of it.

## Run: bridge-analysis#384 resolve 2026-05-18
- → PR #389 MERGED. $1.15, 20 iters, 1.7M in, only +31/−77 LOC (refactor) → 94 LOC/$.
- Status log iters 10 & 15 identical: "Reading the current leaderboard.py to understand the exact code structure before making changes. [Changes: (none)]" — over-exploration signature (a): repeated full-file re-reads of a large notebook before any change.

## Run: bridge-analysis#392 resolve 2026-05-20
- → PR #399 MERGED. $1.61, 30 iters, 4m25s, 2.9M in / 16K out, +97/−30 → 78 LOC/$.
- Cache: 2.7M read, ~$7.34 saved. Distillation: 5.6K → 972 tokens.
- Status log iters 10,15,20,25 are ALL variations of "read/check leaderboard.py to understand structure before making changes" with no committed changes — the clearest mid-May over-exploration example. ~25 of 30 iterations spent orienting on one file.

## Run: bridge-analysis#405 resolve 2026-05-21
- → PR #406 MERGED. $1.30, 18 iters, 1.8M in, +80 LOC across 5 files → 61 LOC/$.
- Pattern repeats: iters 10/15 "check the current state of the files".
- Note LOC/$ collapse on edit-style tasks vs greenfield notebooks (61–94 LOC/$ vs 1–2k LOC/$): cost scales with reading, not writing.

## Run: bridge-analysis#415 resolve 2026-05-23 (tactical-advice notebook)
- → PR #417 MERGED. $2.12, 27 iters, 6m41s, 3.3M in / 22K out, 1007 LOC. Cumulative (incl. workshop+2 design passes): $5.81.
- Cache: 3.0M read, ~$8.07 saved. Distillation 5.6K → 2.2K.
- Iters 10–25 all "[Changes: (none) [+dirty]]" check-current-state loops.

## Run: bridge-analysis#393 resolve 2026-05-23 (hierarchical EB shrinkage)
- → PR #418 MERGED. $1.40, 20 iters, 2.0M in, +73/−15. Cumulative across workshop+design+resolve: $3.06.
- This is the issue where the spec said BT+EB and the agent shipped EB-only (premature-victory example (b), methodology shortcut). Status log shows no hint of the shortcut — log lines look healthy while scope was being silently narrowed. Status logs do not surface failure mode (b).

## Run: bridge-analysis#436 delegate 2026-05-26 (the premature-victory case)
- Invoked `/agent-delegate` with `design_rounds=2 max_iterations=150` (user raised the budget).
- Stages 1–3c (design → council → revision → spec → council → revision): 16m4s, 1.2M in / 50K out, $4.06.
- Stage 4 implementation: ~20 iterations (per distillation line "× 20 iters"), ~6 min → PR #437: 6 schema tables + 4 CLI commands + tests. PR body openly frames it: "I implemented the foundational database and CLI layer" — when the issue wanted a full web app.
- Stage 6 revision: 24 iters, $1.65, +35/−7.
- Pipeline self-reports "✅ Delegate pipeline complete" with all 6 stages checkmarked. Total: 28m45s, 44/150 iterations, 6.5M in, $8.30 agentic + feature total $17.89, Cumulative LOC/$ ~2.
- KEY EVIDENCE on (b): budget was NOT the constraint — agent used 44 of 150 iterations and stopped. Premature victory is a stopping-criterion problem, not a budget problem. Status log shows the standard "check current state" lines, nothing flagging under-delivery.

## Run: bridge-analysis#436 resolve 2026-05-27 (first run after rdb #628 prompt fix)
- → PR #438 (OPEN): 14m27s, 69 iterations, 10M in / 51K out, $5.22, 45 files, +3286 LOC, 629 LOC/$. Cumulative for the feature: $13.16 on this thread's accounting.
- Cache: 9.7M read, ~$26.17 saved (~5× the paid cost). Distillation: 417K → 7.0K tokens, ~$9.59 saved — the delegate mega-thread is where distillation finally pays.
- Direct A/B on the same issue: pre-fix delegate produced a foundation stub; post-fix resolve produced the complete app (FastAPI + HTMX, OAuth/magic-link, precompute, Terraform/nginx/systemd). All 3 council reviewers confirm architecture matches the approved design ("perfectly aligns with the agreed-upon architecture" — gemini-small).
- Iterations 69 = largest in corpus (typical 10–30), evidence for over-correction risk (a)? Partly: status log iters 10–65 are a wall of "Let me check the current state of the repository [Changes: (none) [+dirty]]" every 5 iters — but LOC/iteration (48) is in normal range (#359: 102, #417: 37), and the deliverable was ~5× larger than any other run. Verdict: iterations scaled with scope, not runaway reading; the repetitive status lines are partly a status-summarizer artifact (uncommitted work shows as "(none) +dirty").
- BUT failure mode (b) survived in subtler form: all 3 council reviewers independently caught that `precompute.py` claims "BT-MM fit + EB shrinkage" in docstrings/PR body while `_compute_cohort_rankings` actually implements plain EB-shrunk IMP averages, self-described in a comment as a "pragmatic approximation". Structural completeness was fixed by #628; silent methodology substitution was not — which is precisely what rdb #631 ("Resolve prompt: methodology fidelity, end-to-end verification", merged May 31) targets. #631–633 have ZERO production runs since.

## Run: bridge-analysis#438 review 2026-05-27 (solo + council)
- Solo `/agent-review council=true` 13:41 → detailed single-model review 3 min later (read/write-DB misuse, OAuth state dict issues, next_url validation).
- Second invocation 18:07 → council of 3 posted within 2 min. Verdicts: needs-changes (gpt-small, claude-small), LGTM-minor (gemini-small). High-quality catches incl. the BT+EB mislabel and dead `ALLOWED_EMAILS` config.
- Failure artifact: trailing comment "⚠️ Agent did not complete — partial cost: 57s, 0 iterations, 99K in / 8.5K out, $0.18" posted AFTER "Council code review complete". Looks like a reporting bug in the review job's final status step, not a real failure (reviews all posted).

## Run: bridge-analysis#439 & #440 workshop+design 2026-05-29 (post-#628 design behavior)
- Workshops: Stage 1 ~2–4 min each, Stage 2 council 3 reviewers, clean.
- Design revisions: #439 — 6 iters, 3m31s, 598K in, $1.84; #440 — 5 iters, 2m9s, 452K in, $1.40.
- Pre-#628 design baselines: #393 (May 21) 3 iters $0.75; #415 (May 22) 4 iters $1.14 and 5 iters $1.60. Post-#628 design iterations rose modestly (3–5 → 5–6), cost similarly ($0.75–1.60 → $1.40–1.84). No design-loop blowup.
- rdb issue #630 (May 29, open) filed off run #439: "the cost table doesn't have the number of iterations" — user actively dogfooding the reporting.

## Failures: taxonomy (complete list found)
1. **Provider overload** — ba#364 1st attempt (May 15): litellm InternalServerError "overloaded_error" at iter 1, $0.00, clean failure comment with cost table; manual retry 1h later succeeded. 1 occurrence.
2. **Workshop startup crash** — ba#393 (May 19): "Workshop process exited unexpectedly", 1s wall-clock, 0/15 iterations, $0.00. Re-run next day succeeded. 1 occurrence.
3. **Phantom 'did not complete'** — ba PR#438 (May 27): "Agent did not complete — partial cost" with 0 iterations posted after a fully successful council review; reporting bug, no user-visible work lost. 1 occurrence.
4. **Silent no-op invocations** — rdb#599: four `/dogfood design` comments (Apr 29–30) produced nothing; root-caused by a later design run (workflow trigger path), marked resolved May 17. Pre-May tail.
- Notably ABSENT: no context-window blowups, no wrapup-forced incomplete PRs, no failure comments at all between May 20 and May 29 despite the heaviest usage.

## Patterns and summary

**Verb mix (31 invocations, ba):** resolve 17, design 6, workshop 5, review 2, delegate 1. rdb dogfood: ~0 in May (self-dev moved to local Claude Code; bot usage is now 100% bridge-analysis).

**Typical cost per verb:** resolve $0.35–2.12 (median ~$1.1; outlier $5.22 web app); design $0.75–1.84; workshop Stage1+2 ~$1–2; council review ~$0.2–0.5/reviewer; delegate full pipeline $8.30 agentic / $17.89 feature-total.

**Cost trend (May 5 → May 27):** per-run cost ROSE ~3–10×: $0.49 (May 5) → $0.35–0.57 (May 15) → $0.94–1.29 (May 17–18) → $1.30–2.12 (May 20–23) → $5.22 (May 27). Driver is input-token growth (330K → 10M per run) from bigger issue threads, design-context-as-binding, and repo growth — not per-token inefficiency. Meanwhile cache savings grew faster than cost: $0.36 saved (May 5) → $3–4 (May 17–18, after #621 fixed the formula/marker ~May 15–16) → $7–8 (May 20–23) → $26.17 (May 27): the cache now absorbs 3–5× the paid spend. Distillation is negligible on ordinary issues (5.6K → ~1.5K, $0.03–0.05/run) but decisive on delegate mega-threads (413–417K → 7K, $3.5–9.6/run saved) after the May 23 #626 fixes.

**Economics by task shape:** greenfield notebook generation is spectacularly cheap (1–2k LOC/$); surgical edits to large notebooks are 10–100× worse per LOC (9–94 LOC/$) because cost scales with reading, not writing. The README-metric Info/$ tracks the same gradient (162 → 5 Kbit/$).

**Failure mode (a) over-exploration:** pervasive in MILD form — nearly every status log shows 2–5 consecutive "check the current state / re-read the file" iterations with no committed changes (worst: #392, ~25 of 30 iterations orienting on one large notebook). But absolute waste is bounded (~$0.5–1/run) because cache eats re-reads. Post-#628 over-correction: NOT confirmed — design runs +1–2 iterations; the 69-iteration web-app run scaled with deliverable size. One caveat: only 4 post-#628 runs exist; #631–633's "read the reference implementation" prompts have zero runs.

**Failure mode (b) premature victory:** confirmed and the dominant real problem. Delegate #436 stopped at 44/150 iterations declaring a 6-stage "✅ complete" for a foundation stub; budgets are not the binding constraint, the stopping criterion is. Post-#628 the same issue re-run delivered the full 45-file app (structural completeness FIXED), but the agent still silently downgraded the ranking methodology (claims BT+EB, implements shrunk IMP means, self-labels "pragmatic approximation") — caught by all 3 council reviewers, i.e., the council layer is currently the working defense against (b). The May 31 prompt fixes (#631 methodology fidelity, #632 spec placeholders ban, #633 design acceptance tests) target exactly this residue but have NO production evidence yet — usage stopped May 29; issue #441 (Jun 11) has had no invocation.

**Meta-observation:** the tool's heaviest real-world month shows a maturing loop: human invokes workshop → reads council → invokes design → invokes resolve → invokes council review on the PR. Every one of the 17 resolve invocations except one infra crash ended in a PR, and every agent PR except the open #438 was merged. The product risk is no longer "does it produce PRs" but "does the PR contain what the spec said" — and the cost ceiling per feature (~$18 for the web app including all governance stages) remains far below human cost.
