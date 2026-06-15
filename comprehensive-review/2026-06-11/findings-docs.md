# Docs review findings (Phase 3) — dev branch, 2026-06-11

## README.md
- [STALE] "Security microagent" bullet (~line 396): references a `SECURITY_GATE` marker that does not exist anywhere in agent.yml or remote-dev-bot.yml (grep: zero matches outside README). No "hardened system prompt instructions" against exfiltration exist in lib/resolve.py or the workflow either. "Microagent" is OpenHands-era terminology (OpenHands removed v0.6). Three README references (lines 369, 397, 410) all point at a nonexistent marker; the real gate is the `author_association` check in agent.yml.
- [WRONG] "Opens a draft PR" in How It Works step 3 and "Agent-created branches are draft PRs by default" (Recommendations, ~line 404): default `pr_type` is `ready` (remote-dev-bot.yaml, resolve.py default "ready"). Draft is only for `on_failure: draft` partial-work PRs.
- [STALE] Per-invocation args table: `bash output limit ... default: 8000` — remote-dev-bot.yaml now sets `bash_output_limit: 0` (truncation temporarily disabled). Same stale 8000 default in "Other Configuration Options" YAML block (~line 328).
- [STALE] "Other Configuration Options": `timeout_minutes: 120 ... (default: 120)` — yaml default is 60.
- [STALE] "Other Configuration Options": `context_keep_tool_results` shown as "(default: 10)" with example value 20 — yaml now sets 0 (temporarily disabled, was 20). Internally inconsistent (10 vs 20) and both wrong vs current default 0.
- [STALE] `timeout minutes` listed as type "integer" in per-invocation args table — ALLOWED_ARGS declares it `float` (fractional timeouts shipped).
- [WRONG] "You can also override `max_iterations`, `branch`, and `context` on a per-invocation basis" (~line 336): there is no `context` arg in ALLOWED_ARGS (real names: `max_context_tokens`, `context_keep_tool_results`, ...).
- [GAP] `council = true` inline arg on `/agent-review` (v0.9 headline feature) never mentioned — the Workshop/Build council section exists but review-mode council is absent.
- [GAP] Delegate and reconcile get one table row each but no descriptive section (workshop/build get a full section). Delegate's `max_design_iterations` and `design_rounds` knobs undocumented here.
- [GAP] Distillation pre-pass (`distill_enabled: true` by default — on for every user) not mentioned anywhere in README, including "Other Configuration Options".
- [STALE] Architecture section: reusable workflow "dispatches to resolve, design, or review mode" — workflow now has resolve/build/review/reconcile/design/workshop/delegate jobs.
- [NIT] Model ID examples use `anthropic/claude-sonnet-4-5` (3 places) while the shipped alias is `claude-sonnet-4-6`.

## install.md
- [WRONG] Step 2.3.1 is broken for every new install: tells users to `curl https://raw.githubusercontent.com/gnovak/remote-dev-bot/main/remote-dev-bot.yaml.template` — that file does not exist on main or dev (added in 33e01dd, deleted in 820f891 "Handle RateLimitError..." — looks like an accidental deletion). Live URL returns 404. Either restore the template or rewrite the step.
- [STALE] "opens a draft PR for your review" (Overview), Step 4.3 "Create a draft PR", Step 4.4 "A draft PR linked to the issue" — default `pr_type` is `ready`; successful runs open ready PRs.
- [STALE] Troubleshooting "Agent doesn't trigger": "comment starts with exactly `/agent-resolve`, `/agent-design`, or `/agent-review`" — missing workshop/build/delegate/reconcile verbs.
- Verified OK: agent.yml secret/variable names (RDB_APP_ID, RDB_APP_PRIVATE_KEY, RDB_PAT_TOKEN), explicit-secrets note matches agent.yml header comment, rocket reaction exists in workflow, lib/feedback.py API (InstallReport, add_problem, set_conversation_summary, has_problems, get_consent_prompt, report_problems) all real.

## how-it-works.md
- [STALE] "The compiled install has no visibility requirements since the workflow is self-contained" (Visibility requirements, ~line 249) — the compilation system (scripts/compile.py, dist/) was removed; there is no compiled install. Dangling reference.
- [STALE] Target-repo table (~line 65): shim "Triggers on `/agent-resolve`, `/agent-design`, `/agent-review`, `/agent-workshop`, and `/agent-build`" — missing `/agent-delegate` and `/agent-reconcile` (shim itself matches any `/agent-` prefix, so they work).
- [GAP] "How the Pieces Connect" covers resolve/workshop/build flows but says nothing about delegate (the v0.9 6-stage pipeline) or reconcile.
- [STALE] "Supported arguments" table lists only 4 of 16 ALLOWED_ARGS — presented as the complete list; missing `council`, `bash_output_limit`, `distill_enabled`, `status_log_interval`, `max_design_iterations`, `design_rounds`, compaction knobs, etc.
- [NIT] Model-resolution example resolves claude-large to `anthropic/claude-opus-4-5` — current ID is `claude-opus-4-7`.
- [NIT] Flow diagram ends "Draft PR opened in target repo" — default pr_type is ready (body text above it correctly says "draft (or ready)").

## CONTRIBUTING.md
- Compile-system/OpenHands leftovers: none found (grep compile/dist/openhands = clean; PR #619 cleanup held).
- [WRONG] Config Layering: "Lists replace entirely (no concatenation)" — false for `extra_files`, which is explicitly additive across all four layers with dedup (lib/config.py ~line 522-536, and how-it-works.md documents the additive behavior). True only for other lists (e.g., `council`). Needs an "except extra_files" carve-out.
- [WRONG] Dogfood shim section claims bare `/dogfood` works ("resolve with default model") — dogfood.yml's trigger requires `startsWith('/dogfood-')` or `startsWith('/dogfood ')`, so a comment of exactly `/dogfood` never fires. (dogfood.yml's own header comment has the same wrong claim.)
- [NIT] Process observation: test.yml only triggers on PRs to **main**, but the documented branch model sends every PR to **dev** — so "unit CI green" (release step 1) never actually runs on dev PRs. Docs describe the code accurately; the gap is real either way and worth an issue.
- Verified OK: e2e.sh flags (--provider/--all-models), TestLoopPreventionRegex exists, `.remote-dev-bot/` sparse-checkout path matches workflow, release.yml exists, three-layer config + ALLOWED_ARGS reference accurate.

## AGENTS.md
- [STALE] Project intro + "How It Works" describe only resolve/design/review ("controlled via /agent-resolve, /agent-design, and /agent-review comments"); workshop/build appear in Key Files but reconcile and delegate are absent from the overview entirely.
- [STALE] Key Files: remote-dev-bot.yml "jobs: parse, resolve, design, review, workshop, build" — actual jobs also include `reconcile` and `delegate` (8 total).
- [STALE] "Adding a provider: add API key check to all **five** 'Determine API key' steps (resolve, design, review, workshop, build)" — there are now **seven** such steps (reconcile and delegate added). Stated twice (Key patterns + Common Tasks). Following the doc would leave two modes broken for a new provider.
- [STALE] Python key-files list omits lib/reconcile.py, lib/distill.py, lib/tools.py, lib/formatting.py, lib/generate_index.py, lib/cumulative_cost.py, lib/post_fallback_cost.py (design_loop.py/workshop.py only appear later in the Codebase Index).
- [STALE] Tests list covers 6 of ~20 test files — missing test_distill, test_reconcile, test_tools, test_design_loop, test_workshop, test_no_op, test_context, test_resolve_recovery, test_cache_distill_savings, etc.
- [GAP] No description of the delegate pipeline (stages, max_design_iterations/design_rounds) or the distillation pre-pass in the Codebase Index — both are places an agent working on this repo would look.
- [NIT] test_syntax.py described as checking "lib/ and scripts/" — scripts/ no longer exists (compile-system residue); the test tolerates the missing dir, but its docstring and AGENTS.md both still reference it.

## CLAUDE.md
- clean (two-line pointer to AGENTS.md and ~/.config/agents/AGENTS.md; both exist)

## debug.md
- [STALE] `bash_output_limit` "Default: 8000" — remote-dev-bot.yaml now ships `0` (truncation disabled for baseline data gathering).
- [STALE] `context_keep_tool_results` "Default: 20" — yaml now ships `0` (disabled, was 20).
- [GAP] README defers "tuning and observability options" to debug.md, but debug.md omits: `distill_enabled` (on by default!), `debug_logging`, `design_context_keep_tool_results` / `review_context_keep_tool_results` (all in ALLOWED_ARGS), fractional `timeout_minutes`, and the distillation/cache-savings summaries that now appear in the status-log comment (lib/formatting.py build_distillation_summary / build_cache_savings_summary).
- Verified OK: status log mechanics (side-channel call, posted as one issue comment at end — matches resolve.py), compaction resolve-only claim (design_loop.py has trim_tool_results but no compaction), compaction defaults/0.85 trigger, smart drop order (read-only first) matches context.py behavior, GITHUB_STEP_SUMMARY table exists.
- [WRONG] Correction to "Verified OK" above: debug.md's drop-order example "read-only results (file reads, grep) are dropped first" is backwards — lib/context.py explicitly PROTECTS read_file and grep results ("reference material — protect them like write ops"); only read-only *bash* command results (ls, cat, git log) are dropped first.

## onboarding.md
- [GAP] No exercises (or even a mention) for workshop, build, delegate, reconcile, or council review — the entire v0.9 feature set. Closing line "You've now used all the main features of remote-dev-bot" is now false; at minimum add a "there's more" pointer.
- Otherwise accurate: resolve/design/review/iteration flows, rocket reaction, cost comment, model-variant guidance all match current behavior.

## demo.md
- [STALE] "The Three Modes" table presents resolve/design/review as the complete mode list — there are now seven modes (workshop, build, delegate, reconcile missing). Header itself ("Three Modes") is wrong.
- [GAP] No examples for the v0.9 marquee flows (delegate, council review, reconcile) — this is the pre-install showcase page, the natural place to sell them.
- Examples 1-3 reference real issues/PRs and match README's; no factual issues otherwise.

## CHANGELOG.md
- [GAP] v0.9.0 entry omits several user-visible changes that are on dev and will ship with the tag: distillation pre-pass (`distill_enabled: true` — ON by default for all users), Anthropic prompt-cache markers + cache-savings reporting in status comments, fractional `timeout_minutes`, and the config default flips `bash_output_limit` 8000→0 and `context_keep_tool_results` 20→0 (cost-relevant for every user). Human pare-down is policy, but default-behavior changes belong in the entry.
- Verified OK: v0.9 delegate 6-stage description matches code/yaml; "council ... in parallel" is correct (ThreadPoolExecutor in lib/workshop.py — workshop, build, and delegate councils all parallel); release.yml `^## v<version>` extraction matches header format; historical entries left as history.

## how-it-works.md (addendum)
- [WRONG] "lib/workshop.py runs each council model in sequence" — councils run in PARALLEL via ThreadPoolExecutor (workshop.py lines ~495, ~755 "Run council reviews simultaneously", ~1296). CHANGELOG v0.8/v0.9 correctly say parallel.

## design-workspace.md (scratchpad — lighter standard)
- [STALE] "Current token-saving measures" table marks tool-result trimming (keep 20) and bash truncation (8000) as **Active** — both are now 0/disabled in remote-dev-bot.yaml (the doc's own later sections say so; the table was never updated). Misleading to a reader scanning the table.
- [STALE] Row 6 "Cache marker — single, on initial user msg — Insufficient" — the moving-tail cache_control marker has since shipped (resolve.py ~1355-1513), so the assessment is resolved, not pending. Open question #1 (do explicit markers help?) is likewise settled by the implementation.
- [NIT] Sections C and F are the same proposal (raise/remove bash_output_limit) pasted twice.

## .gemini/GEMINI.md
- clean (one-line pointer to AGENTS.md; target exists)

## Top findings (Phase 3)
1. [WRONG] install.md Step 2.3.1: `remote-dev-bot.yaml.template` curl URL 404s — file was deleted (820f891, apparently accidentally). Breaks every fresh install at the config step. Fix before May 12 release.
2. [STALE] README Security section cites a `SECURITY_GATE` marker and "security microagent" hardened prompt that do not exist anywhere in the code (OpenHands-era residue). A documented-but-nonexistent security mitigation is the worst kind of doc rot.
3. [WRONG] "Draft PR by default" claims in README (2x) and install.md (3x) — default pr_type is `ready`. Sets wrong user expectations about review safety.
4. [STALE] AGENTS.md provider recipe says update "all five" Determine-API-key steps; there are seven (reconcile, delegate added). Following the doc ships a provider broken in two modes. Same doc's job list also omits reconcile/delegate.
5. [STALE] Default-value rot across README + debug.md: bash_output_limit "8000" (now 0), context_keep_tool_results "10"/"20" (now 0), timeout_minutes "120" (now 60).
6. [GAP] v0.9 features invisible where users look: `council=true` review absent from README; delegate/reconcile have no prose anywhere user-facing; onboarding.md claims "all the main features" covering only 3 of 7 modes; demo.md's "The Three Modes".
7. [GAP] Distillation pre-pass is ON by default for every user yet appears in no user-facing doc (README, debug.md, how-it-works) and not in the v0.9 CHANGELOG entry; ditto the 8000→0 / 20→0 default flips.
8. [WRONG] CONTRIBUTING "Lists replace entirely (no concatenation)" contradicts code + how-it-works (extra_files is additive); and how-it-works "council in sequence" contradicts code + CHANGELOG (parallel). Docs disagree with each other, code settles both.
9. [WRONG] Bare `/dogfood` documented in CONTRIBUTING (and dogfood.yml's own header) but the trigger requires `/dogfood-` or `/dogfood ` — exact `/dogfood` never fires.
10. [WRONG] debug.md drop-order example backwards: says file reads/grep dropped first; code protects them and drops read-only bash results first.

**Overall doc health:** Core resolve/design/review flows, security gating, auth, and dev-cycle docs are solid and verified accurate — but the doc set lags ~2 releases on config defaults and v0.9 features, with one install-breaking 404 and one phantom security claim that should block the release. Tag counts: 7 WRONG, ~21 STALE, 9 GAP, 6 NIT across 12 docs (2 clean).
