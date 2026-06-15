# remote-dev-bot — Comprehensive Review (2026-06-11)

Written 2026-06-11 against dev @ de72856 (PRs #631-633 merged). Synthesizes
five phases of incremental findings written by sequential subagents and
preserved alongside this file: `findings-{code,workflows,docs,usage,prompts}.md`.
Numbers and file:line cites come from those files; consult them for the
long-form evidence behind each item below.

---

## 1. Executive summary

rdb has reached a **maturing product** stage. The May 2026 usage record
(31 real invocations on bridge-analysis) shows the tool dependably produces
merged PRs from natural-language issues at ~$0.50–$2 per typical run and
$5–$13 per large feature, with prompt-cache savings now 3–5× the paid spend.
The original failure mode you set out to solve — agent-as-pair-programmer
requiring synchronous attention — is solved: every May invocation except one
provider outage produced a PR; every PR except one (the open web app) merged.

Three concerns dominate the current state:

1. **A handful of real, exploitable defects that should be fixed before any
   external adoption.** Two are user-data-driven injection vectors (one shell,
   one Python); one breaks every fresh install; one silently disables
   distillation for `/agent-design`; one prevents unit tests from running on
   the dev-branch PRs that *are* the development model. None are theoretical;
   most are one- to several-line fixes.

2. **The product risk has shifted from "does it produce a PR" to "does the PR
   contain what the spec said."** Premature-victory cases (bridge-analysis
   #437 schema stub; #438 silent BT-MM → EB-shrunk-averages methodology
   substitution) survived after `/agent-delegate` self-reported "✅ complete."
   PR #628 fixed structural completeness; PRs #631-633 (merged May 31, no
   production runs yet) target the methodology-substitution residue. The
   **council layer is the current working defense** against this — and it's
   open-loop, advisory only.

3. **Doc and workflow drift has accumulated past the point where users can
   self-serve.** 7 outright-wrong claims (incl. a phantom security mechanism),
   ~21 stale references, 9 v0.9 features absent from places users look.
   Several workflow jobs have drifted away from shared lib/ helpers and
   silently regressed (design lost caching, reconcile lost config plumbing).

The prompt stack is in good shape but unvalidated since the May 31 changes.
Recommendations are below in priority order.

---

## 2. Where rdb is

### What's working

- **Delegation that survives walking the dog.** The model you set out for —
  dictate idea on phone, agent comes back with a PR — works. 16 of 17 May
  resolve runs landed a PR; the one exception was a transient provider
  overload, not an agent failure.
- **PR-as-output as the human gate.** Universal: every agent PR was reviewed
  before merge; the gate caught the methodology shortcut on PR #438 (via the
  council pass, not human eyeballs).
- **Cache savings now dominate cost.** After the moving-tail cache marker was
  restored (~May 16, rdb #621), cache savings grew from $0.36/run (May 5) to
  $26/run on the May 27 delegate (5× the paid spend). The "cost of using rdb"
  question is largely solved for steady-state usage.
- **Multi-model councils are doing real work.** On bridge-analysis #438 all
  three council reviewers independently caught the BT vs EB methodology
  substitution that the agent had buried in a docstring. The cost of three
  parallel reviews (~$1) bought a quality catch that a human reviewer might
  reasonably miss.
- **Model-agnosticism is intact.** Prompts are plain English. Cache markers
  are provider-gated in code, not prompt text. Tool-calling goes through
  litellm's normalized contract. The architecture supports model-swapping
  cleanly today.

### Where the cracks are

- **Premature victory is the dominant residual defect.** Budgets are not the
  binding constraint — bridge-analysis #436's delegate run used 44 of 150
  iterations before declaring "✅ Delegate pipeline complete" on a 632-LOC
  schema stub of what should have been a full web app. The stopping criterion
  is the problem, not the budget.
- **Over-exploration is real but bounded.** Roughly 2–5 of every 10–30
  iterations are "let me check the current state of <file>" with no committed
  changes. Worst observed: ba#392 used ~25 of 30 iterations orienting on one
  notebook. Cache eats most of the cost (~$0.5–1/run waste), so this is mild
  in absolute terms — but it is a real signal that the agent's
  "am-I-done-reading?" heuristic is weak.
- **Doc rot has reached install-breaking severity.** `install.md` references
  a config template deleted in an unrelated commit (820f891). Every fresh
  install 404s. Plus 9 v0.9 features (delegate, reconcile, council reviews,
  distillation, fractional timeouts, cache markers) are barely mentioned in
  user-facing docs.

### What the workflow regressions tell us

The `/agent-design` standalone job never adopted `lib/design_loop.py` —
the module whose docstring claims to be the extraction target for this
exact case. Consequence: every design-prompt improvement (the gh tool,
budget hint, retries, cache markers, distillation fixes) shipped only for
workshop and delegate. Standalone `/agent-design` runs at 0% cache hit on
Anthropic and pays full repo context every run. Reconcile similarly has
drifted away from shared config plumbing.

The pattern is clear: **half-finished migrations are how rdb regresses.**
The accepted-duplication strategy in `.github/workflows/remote-dev-bot.yml`
(8 jobs, intentional setup-block duplication after PR #611's composite-action
reversion) is working for the setup blocks. It is not working for the
heredoc-vs-lib boundary — that's where every drift has landed.

---

## 3. Defects worth fixing before wider use

Ranked by combined severity × likelihood. file:line cites point to the live
defect; the findings files have full reasoning.

### Tier 1 — ship-stoppers / security

| # | Location | What | Fix size |
|---|---|---|---|
| T1.1 | `lib/resolve.py:1104` | LLM-authored `pr_title` interpolated into `shell=True gh pr create` with only `"` escaping; backticks and `$(...)` remain live. Issue body is the upstream source. | argv list or `shlex.quote` |
| T1.2 | `.github/workflows/remote-dev-bot.yml:1173, 1599-1605, 2018, 3374-3375, 3675-3676, 4006` | Target-repo `extra_instructions` interpolated as Python literals inside heredocs (5 of 8 jobs). Multi-line YAML block scalars (the documented format) crash with SyntaxError; arbitrary Python is executable from target-repo config. | Route through `env:` like resolve does |
| T1.3 | `install.md` Step 2.3.1 | `curl` URL to `remote-dev-bot.yaml.template` returns 404 (file deleted in 820f891). Every fresh install breaks here. | Restore template or rewrite step |
| T1.4 | `.github/workflows/test.yml:5` | `pull_request: branches: [main]` only — but the documented branch model is dev-only PRs. PRs #631-633 merged with zero CI. | Add `dev` to branches list |

T1.1 and T1.2 are the security items. Both are reachable from data a third
party can inject (issue/PR body for T1.1; target-repo `remote-dev-bot.yaml`
for T1.2). The README claims a `SECURITY_GATE` marker and a "security
microagent" hardened prompt — neither exists in the codebase. Phantom
security mitigation is doc rot worth fixing alongside the real ones; it
sets up an external reader (or yourself in six months) for a false sense
of safety.

### Tier 2 — real bugs that materially degrade behavior

| # | Location | What |
|---|---|---|
| T2.1 | `lib/resolve.py:1523` | `ContextWindowExceededError` subclasses `BadRequestError`; the BadRequest handler comes first → CWE recovery is dead code. Overflowing runs die with "Bad request" instead of force-trim + graceful wrap-up. |
| T2.2 | `.github/workflows/remote-dev-bot.yml:2753` | Heredoc unpacks 5 values from `maybe_distill()` which returns 6 → ValueError swallowed → every `/agent-design` run pays full-repo cost. Workshop/delegate stage 1 unaffected (use lib/). |
| T2.3 | Parse outputs missing | `design_max_iterations` and `review_max_iterations` emitted by `config.py` but never declared as parse-job outputs. Design loops run 10 iterations (hardcoded default) instead of configured 15; design wrapup (fires at 12) can never trigger. Per-invocation `max_iterations=` overrides silently ignored for design/review. |
| T2.4 | Reconcile job env block (workflow ~2289-2307) | `BASH_OUTPUT_LIMIT`/`CONTEXT_KEEP_TOOL_RESULTS`/`MAX_CONTEXT_TOKENS`/`COMPACTION_*` consumed by lib/reconcile.py but never set in the job env → reconcile runs with truncation=8000 and cache-defeating keep_n=10 against config-mandated 0s. |
| T2.5 | `lib/resolve.py:1632`, `lib/reconcile.py:598`, `lib/design_loop.py:421` | Cache-write tokens read via `getattr(prompt_details, "cache_creation_input_tokens", 0)` — litellm's field is `cache_creation_tokens`. Always returns 0. "Tokens written to cache" never appears in status logs; cache-savings formula overstates because write overhead is never subtracted. |
| T2.6 | `lib/resolve.py:1002-1076` | resolve.py runs a stale local `trim_tool_results` that drops oldest results without the read/write-aware ordering its siblings get from `lib/context.py`. The code-writing loop — the one where protecting write results matters most — is the one missing the protection. The current test suite covers the lib/context.py version, so this is invisible to CI. |
| T2.7 | `lib/resolve.py:1657`, `lib/reconcile.py:609` | "No tool calls for 3 consecutive iterations" break writes no status file, but the post-loop logic only writes status when `loop_completed_naturally` is True → runs end with no failure explanation. |
| T2.8 | `lib/distill.py:296` | `ast.get_source_segment(source, node.args)` always returns None (ast.arguments carries no position attrs). Every structural-extract signature degrades to bare positional arg names — defaults, kwonly, `*args`, `**kwargs`, annotations all dropped. Fix: `ast.unparse(node.args)`. |

### Tier 3 — drift between sibling loops

Resolve/reconcile/design_loop share patterns but have drifted such that each
got a fix the others didn't:

- **Wrapup mechanics:** resolve re-injects every iteration past threshold;
  reconcile injects exactly once; design_loop injects once via flag. Three
  loops, three implementations of the same nudge.
- **Transient-error retry wrapping:** design_loop uses
  `completion_with_retries`; reconcile uses bare `completion()` → a single
  Anthropic 529 "overloaded" kills a reconcile run that the siblings would
  survive.
- **Moving-tail cache markers:** resolve and reconcile have them;
  design_loop doesn't → design/workshop stage 1 on Anthropic pays full
  input price every iteration.
- **Compaction logic** (`lib/context.py:330`): the boundary-cut in
  `compact_messages` can split an assistant(tool_calls) message from its
  role="tool" results, leaving orphan tool results that providers reject
  with a 400. Affects resolve and reconcile compaction paths.

### Tier 4 — workshop/delegate-specific

- **Delegate Stage 3 vs Stage 3c inconsistency** (`lib/workshop.py:1379`):
  if the revision contains an `/agent` command, Stage 3c nulls the artifact
  but Stage 3 only suppresses posting — the contaminated revised_design
  still flows to Stages 3a/4. "Blocked for safety" message is cosmetic.
- **Delegate design-stage wrapup never fires** (`workflow:3643` →
  `workshop.py:1192`): `graceful_wrapup_iteration` = 40 (= 0.8 × code budget
  50) is passed unchanged into 15-iteration design stages. The
  wrap-up-now nudge is unreachable in design.
- **Distillation cost dropped from workshop/delegate totals** (workshop.py
  846-854, 1200-1202, 1447-1449): only loop costs summed, not
  `distill_input_tokens`/`distill_cost`. resolve.py seeds totals correctly;
  workshop/delegate under-report.

---

## 4. Prompt recommendations (synthesizing Phase 5)

The full reasoning is in findings-prompts.md. Headlines:

1. **Close the council loop.** Today: delegate Stage 5 posts council reviews,
   Stage 6 posts a "revision plan," nothing acts on the findings. On bridge
   #438 the council unanimously caught the BT-MM substitution and the
   pipeline marked itself "✅ complete" anyway. Closing the loop (council
   findings triaged into blocking vs advisory → blocking triggers one bounded
   revision resolve pass) would convert ~$1 of council spend into a real
   quality gate. This is a code feature, **higher leverage than any further
   prompt tuning.**

2. **Validate the May 31 prompts before further changes.** PRs #631-633
   (methodology fidelity, end-to-end verification, write tests for new code)
   have zero production runs. Pre-#631 data says over-exploration was real
   but cache-bounded (<$1/run waste); the new prompts explicitly encourage
   large reads ("read the 1500-line reference notebook end-to-end"). Expected
   cost is low but should be measured. Watch the first few delegate/resolve
   runs after the next release for iteration counts and cost vs May
   baselines.

3. **Migrate `/agent-design` to lib/design_loop.py.** Precondition for any
   prompt work on the design verb to actually deploy. Current state: `gh`
   tool, budget paragraph, retries, cache markers, and distillation fixes
   are all in the lib but not in the standalone-design heredoc. This is the
   workflow's largest remaining lib-duplicate.

4. **Don't add a Stage 4½ structural-completeness checker.** Tempting — and
   it would target premature-victory cleanly — but it would conflict with
   the model-agnosticism goal (it'd be a separate LLM call with its own
   prompt). The council-loop closure (#1 above) covers the same ground and
   exists already.

5. **Don't re-add the "20-30 iterations is plenty" minimalism language.**
   It was correct under the April cost regime (no caching, dropped tool
   calls). Under May+ caching it produces premature victory. The May 31
   prompts removed it for a reason; usage data confirms the call.

6. **Consolidation pass on the resolve prompt stack** (lower priority).
   Today's resolve system prompt = AGENT_ROLE + SCOPE +
   METHODOLOGY_FAITHFULNESS + DEVIATION_REPORTING + budget + repo context +
   WORKFLOW + TESTS + END_TO_END + READING_THE_TASK + task +
   GIT_INSTRUCTIONS + EFFICIENCY + STUCK_RECOVERY + SECURITY_RULES. Coherent
   today; each future edit risks introducing contradictions between
   overlapping sections. A pass merging WORKFLOW.Verify with END_TO_END, and
   EFFICIENCY.completion with SCOPE.completion, would shrink tokens ~30%
   and the drift surface to match. Small-model compliance (gpt-small,
   gemini-small) with the current long stack is untested; would be
   measurable as part of the validation in #2.

---

## 5. Future directions worth considering

Ordered by what would most expand what rdb can do for you, given your stated
goal (dictate idea → walk dog → review PR).

### A. Voice-friendly trigger surface

You wrote the original goal as "dictate an idea for a feature into the phone
by voice." GitHub mobile's comment field is fine for typing but bad for
dictation (autocorrect mangles slash commands; no template). One thin add
would be a `/dictate <freeform>` verb that:

- accepts any freeform first-line (no strict syntax)
- runs `/agent-workshop` if the prose looks like a feature request, or
  `/agent-resolve` if it looks like a bug report (heuristic: regex for
  "bug/broken/error/crash" → resolve, else workshop)
- posts a one-line "interpreted as: /agent-workshop" comment so you can
  course-correct

Cost: small (probably an addition to the parse job and a routing branch).
Removes the cognitive load of remembering which verb to use when you're
half-asleep on a train.

### B. Council-driven revision (the closed loop from §4.1)

Already argued above as the highest-leverage prompt-adjacent change.
Restating here as a future feature because it requires real implementation
work, not just prompt edits.

### C. Spec-extraction pre-step for `/agent-resolve`

When you `/agent-resolve` on a long-running issue that has accumulated
design comments (the bridge #436 pattern), there's a SCOPE prompt that
tells the agent "treat the most recent revised version as the binding
contract." It works (per #438) but it's a prompt-level instruction the
agent might or might not follow. A pre-step that mechanically extracts
"latest spec section" → a separate prompt input would be more robust and
less model-dependent.

### D. Per-repo "what is rdb good at" memory

The usage data shows extreme variance in LOC/$ by task shape: 1-2k LOC/$
on greenfield notebook generation, 9-94 LOC/$ on surgical edits. A simple
per-repo profile ("this repo's average run cost is $X for tasks of shape Y")
posted as part of the cost comment would let you calibrate which work to
delegate vs do yourself.

### E. Status-log "I'm stuck" signal

Failure mode (a) — over-exploration — shows up reliably in status logs as
3-5 consecutive "let me check the current state of <file>" entries with no
committed changes. A side channel that detects this pattern at runtime and
posts a single "agent appears to be re-reading; intervene if you have new
context" issue comment would let you intervene before iterations are wasted.
Costs: nothing, it's pattern-matching against existing status logs.

### F. The dogfood gap

Usage data shows ~zero rdb dogfood in May — self-dev moved to local Claude
Code. That's likely the right choice for short tight loops, but it means
rdb only sees one real consumer (bridge-analysis), and behavior changes
that work well there might not generalize. A second consumer repo
(perhaps a smaller throwaway, or one of your other private projects)
would give the prompt-validation work in §4.2 broader signal.

---

## 6. Recommended next actions

In order, with rough effort estimates:

1. **Tier 1 fixes** (T1.1-T1.4): ~half a day total. Ship before any wider
   adoption. T1.4 alone restores CI on dev PRs which makes everything else
   safer to merge.
2. **Tier 2 fixes**, especially T2.1-T2.4: another half-day. T2.2
   (distillation broken in design) and T2.4 (reconcile config plumbing) are
   silently regressing costs every run.
3. **Doc patch pass**: ~2 hours. README "Draft PR by default" claims; the
   phantom `SECURITY_GATE`; `/agent-delegate` and `/agent-reconcile` in
   user-facing docs; config defaults across README + debug.md.
4. **Migrate `/agent-design` job to lib/design_loop.py**: bigger, ~half a
   day, but converts the largest standing lib-vs-heredoc drift into a thin
   wrapper. Pays dividends on every future prompt change.
5. **Validate the May 31 prompts on bridge-analysis** before any further
   prompt tuning: trigger a delegate run on an open issue, watch iteration
   count and cost trend vs May baselines.
6. **Close the council loop** as the next feature: highest-leverage product
   change for the residual quality risk.

This sequence trades minimum total work for maximum reduction in the
"don't share with others yet" risk profile.

---

## 7. What's not on this list

Things the review specifically found OK or out of scope:

- Sibling-style imports vs entry-point bootstrap pattern (deliberate; tested).
- e2e tests being shell scripts (deliberate; costs real money).
- The dogfood gate in workflows (working as intended).
- `maybe_distill` 6-tuple return (deliberate; the bug is the heredoc that
  unpacks 5).
- The accepted setup-block duplication across 8 workflow jobs (working).
- CLAUDE.md, .gemini/GEMINI.md, e2e-security.yml (all clean).
- `app-id` → `client-id` GitHub-action deprecation (already tracked
  in issue #618).

---

*End of synthesis. Source detail in
findings-{code,workflows,docs,usage,prompts}.md alongside this file.*
</content>
