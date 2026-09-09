# Subagent prompts used for the 2026-06-11 comprehensive review

Archived for the record and to serve as a starting template for future reviews.
The findings files written by these subagents are alongside this one.

If reusing these prompts: each phase writes incrementally to a findings file
on disk, so a crashed run can resume — re-launch the phase's subagent with
"A previous run was interrupted. Findings so far are in `<findings-file>`.
Read it first and RESUME after the last completed unit — do not redo
completed units." prepended to the prompt.

---

## Phase 1 — lib/ code review (general-purpose agent)

Review the Python library code of remote-dev-bot at /home/novak/code/remote-dev-bot (verify you are on the dev branch with `git branch --show-current` — do NOT switch branches or modify any repo files).

Context: rdb is a GitHub Actions tool — users comment `/agent-<verb>` on issues/PRs and an LLM agent acts (opens PRs, posts design analyses, runs multi-model review councils). lib/ holds the agent loops: resolve.py (code-writing agent), reconcile.py (rebase/conflict agent), design_loop.py (read-only exploration), workshop.py (multi-model councils + delegate pipeline), distill.py (context pre-compression), config.py (3-layer config merge + inline args), context.py (compaction/trim/retry helpers), tools.py (shared tool executors), formatting.py (cost tables), cumulative_cost.py, post_fallback_cost.py, generate_index.py.

YOUR TASK: file-by-file review of every lib/*.py for:
- [BUG] real defects (logic errors, unhandled edge cases that can fire, broken plumbing)
- [STALE] comments/docstrings that no longer match the code or reference removed features
- [DRIFT] divergence between sibling modules that share patterns (resolve/reconcile/design_loop share: budget paragraphs, status logs, cache markers, write_usage, wrapup logic — flag where one got a fix the others didn't)
- [SMELL] silent exception swallowing that could hide real failures, dead code, unused params
- [NIT] minor (only if quick to note)

Things that are INTENTIONAL — do not flag:
- Sibling-style imports (`from formatting import ...`) in library modules vs `from lib.X import` + sys.path bootstrap in entry points (resolve.py, reconcile.py, post_fallback_cost.py). Both deliberate; see tests/test_production_imports.py.
- maybe_distill returning a 6-tuple.
- e2e tests being shell scripts (deliberate, they cost real money).
- The dogfood gate in workflows.

CRITICAL PROTOCOL: After EACH file you finish reviewing, IMMEDIATELY append your findings for that file to <workspace>/findings-code.md using this format:

    ## lib/<name>.py (NNN lines)
    - [BUG] file:line — description
    - [STALE] file:line — description
    (or "- clean" if nothing found)

Write after every file — do not batch. If findings-code.md already has entries when you start, resume after the last completed file.

After lib/, do a LIGHT skim of tests/*.py for staleness only (test names/docstrings referencing removed behavior; do not deep-review 700 tests). Append a final "## tests/ skim" section.

Finish with a "## Top findings" section: the 5-10 most important items, ranked. Be concise throughout — findings, not essays. Do not fix anything.

---

## Phase 2 — workflows + config review (general-purpose agent)

Review the GitHub Actions workflows and config of remote-dev-bot at /home/novak/code/remote-dev-bot (dev branch — verify with `git branch --show-current`, do not modify repo files).

Context: same tool as Phase 1. The main reusable workflow .github/workflows/remote-dev-bot.yml is ~4400 lines with 8 jobs (parse, resolve, design, review, workshop, build, reconcile, delegate). The 8 jobs contain INTENTIONALLY duplicated inline setup blocks (token + checkouts + python) — a composite-action refactor failed for external callers (PR #611 reverted it). The duplication itself is accepted; what matters is DRIFT between the duplicated blocks.

Files to review: .github/workflows/remote-dev-bot.yml, agent.yml, dogfood.yml, test.yml, full-test-suite.yml, e2e.yml, e2e-security.yml, release.yml; remote-dev-bot.yaml (the config); tests/e2e.sh.

Look for:
- [DRIFT] differences between the 8 jobs' duplicated setup blocks (one got a fix others didn't)
- [DRIFT] Python heredocs inside the workflow that duplicate lib/ logic and may have drifted from it (e.g., cost-table heredocs vs lib/formatting.py)
- [STALE] comments that no longer match reality. SPECIFICALLY check remote-dev-bot.yaml's "Temporarily disabled (was N) to gather baseline data" comments on bash_output_limit / context_keep_tool_results / max_context_tokens — baseline gathering was months ago, caching+distillation have since landed; flag whether these should be re-enabled.
- [BUG] env vars consumed by lib/ but not plumbed in some job; outputs set but never read; conditions that can't fire
- [SMELL] anything else notable

Known/already-tracked — do not flag: app-id→client-id deprecation (issue #618 filed); awk-based TIMEOUT_SECONDS (intentional, fractional support); tightened e2e assertions (recent, deliberate).

CRITICAL PROTOCOL: append findings to <workspace>/findings-workflows.md after EACH file (and for remote-dev-bot.yml, after EACH job section). Same format as: "## <file or job>" + tagged bullets. Resume-aware: if the file already has entries, continue after the last unit. Finish with "## Top findings" (ranked). Concise. Read-only except the findings file.

---

## Phase 3 — documentation review (general-purpose agent)

Review all the documentation of remote-dev-bot at /home/novak/code/remote-dev-bot (dev branch; read-only except your findings file).

Files: README.md, CONTRIBUTING.md, AGENTS.md, CLAUDE.md, install.md, how-it-works.md, debug.md, onboarding.md, demo.md, design-workspace.md, CHANGELOG.md, .gemini/GEMINI.md.

For each doc, cross-check its claims against the current code (use grep/read on lib/, workflows, remote-dev-bot.yaml). Hunt for:
- [STALE] features described that no longer exist, or that changed (model IDs/aliases, verb lists missing reconcile/delegate, config knobs with wrong defaults, install steps that don't match agent.yml, references to removed compilation system, OpenHands references)
- [GAP] recently-shipped features that docs never mention (v0.9 additions: delegate, reconcile, council reviews on /agent-review, distillation, cache markers, methodology-fidelity prompts)
- [WRONG] factually incorrect statements
- [NIT] minor

Notes: CONTRIBUTING.md's compile-system references were cleaned recently (PR #619) — verify nothing was missed rather than assuming. design-workspace.md is a working scratchpad — hold it to a lighter standard (flag only actively-misleading content).

CRITICAL PROTOCOL: append to <workspace>/findings-docs.md after EACH doc: "## <file>" + tagged bullets (or "- clean"). Resume-aware. Finish with "## Top findings". Concise.

---

## Phase 4 — real-world usage analysis (general-purpose agent)

Analyze the real-world usage of remote-dev-bot across two repos using the gh CLI (read-only; you have gh access): gnovak/remote-dev-bot (self-dev, invoked via /dogfood-* comments) and gnovak/bridge-analysis (the real consumer, invoked via /agent-* comments).

Goal: an evidence-based picture of how the tool performs in practice, May-June 2026. The two chronic failure modes to look for evidence of: (a) OVER-EXPLORATION — agent burns iterations/cost reading without producing; (b) PREMATURE VICTORY — agent declares success with partial work (e.g., bridge-analysis PR #437: 632-LOC stub when the spec wanted a full web app; PR #438's methodology shortcut). Recent prompt fixes (rdb PRs #628, #631-633) tried to address (b) — look for any runs AFTER ~May 31 that show whether the fixes helped or whether (a) got worse (over-correction risk).

What to gather (SAMPLE, don't be exhaustive — budget matters):
1. Inventory: list issues/PRs with /agent or /dogfood invocations in both repos (gh search or list + grep comments). Tabulate: date, repo, verb, outcome (PR merged / PR open / failure comment / no-op).
2. For ~10-15 representative runs: pull the Agent Status Log comments and 💰 Cost tables. Record: iterations used vs budget, input/output tokens, cache savings line, distillation line, cost, LOC/$, Info/$, wall-clock.
3. Failures: find "could not fully resolve" / "exited unexpectedly" comments — categorize causes.
4. Cost trend: compare early-May costs vs late-May/June (cache marker restoration merged ~May 16, distillation fixes ~May 23) — did per-run cost or cache-savings improve?

Avoid downloading full Actions run logs (huge) — issue/PR comments contain the status logs and cost tables, which is enough. Only pull an Actions log if a specific failure needs root-cause confirmation, max 2-3 of those.

CRITICAL PROTOCOL: append to <workspace>/findings-usage.md INCREMENTALLY: first the inventory table (write it as soon as built), then "## Run: <repo>#<num> <verb>" mini-records one at a time as you analyze each, then final "## Patterns and summary". Resume-aware: if the file has entries, continue after the last run analyzed. Concise.
