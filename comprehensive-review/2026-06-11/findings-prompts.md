# Phase 5 — Prompt analysis

Written by the main session (has full history context: co-authored most of the
current prompt stack across PRs #613, #628, #631-633).

## 5.1 The exploration ↔ completion tension — history and current state

The prompt stack has swung twice:

1. **Era 1 (Feb-Apr): cost-driven minimalism.** "Read only the files you are
   about to change", "a complex multi-file change rarely needs more than 20-30
   iterations", "call finish() as soon as the task is done." Added when tool-call
   trimming and bash truncation were active and every token was paid full price.
   Produced the *premature victory* failure mode (bridge-analysis PR #437:
   632-LOC stub from a full web-app spec, using only 44 of 150 iterations).

2. **Era 2 (May 31, PRs #628/#631): completion-driven expansiveness.** SCOPE
   (spec-in-comments is the binding contract), METHODOLOGY_FAITHFULNESS (port
   reference implementations exactly or finish(success=False)), TESTS,
   END_TO_END, softened budget language ("read the 1500-line notebook
   end-to-end — that's the work").

**Risk: era 2 is unvalidated and may over-correct.** Usage data shows zero
production runs after May 31. Pre-#631 data says over-exploration was real but
*mild and cache-bounded* (<$1/run waste; worst case ~25/30 iterations
orienting). Post-#631 prompts explicitly encourage large reads. Cache pricing
makes reads cheap, so the expected cost of over-correction is low — but it
should be *measured*, not assumed. First few delegate/resolve runs after the
next release deserve a manual look at iterations + cost vs. the May baselines.

**Deeper observation: both eras attack the wrong variable.** The usage data
shows stopping is a *criterion* problem, not a budget problem. Era 1 said
"stop early"; era 2 says "don't stop early"; neither gives the model a
*decision procedure* for "am I done?". The current best answer is prose
("every file, route, table, test the spec lists"). A structural answer would
be stronger — see recommendations.

## 5.2 Model-agnosticism assessment

Goal (per Greg): prompts should be model-agnostic so models can be swapped
freely. Current state: **mostly good, with growing pressure.**

- ✅ All prompts are plain English; no Anthropic-specific tokens/markup.
- ✅ Tool-calling contract (finish/no_op/submit_analysis) goes through litellm's
  normalized function-calling — works across the three providers.
- ✅ Cache markers are provider-gated in code (`model.startswith(("anthropic/",
  "claude", "gemini/", ...))`), not baked into prompt text.
- ✅ `model_extra_instructions` config gives a per-model escape hatch.
- ⚠️ **Prompt length is the emerging risk.** resolve.py's system prompt now
  stacks: AGENT_ROLE + SCOPE + METHODOLOGY_FAITHFULNESS + DEVIATION_REPORTING +
  budget + repo context + WORKFLOW + TESTS + END_TO_END + READING_THE_TASK +
  task + GIT_INSTRUCTIONS + EFFICIENCY + STUCK_RECOVERY + SECURITY_RULES.
  Frontier models handle this; small models (gpt-small, gemini-small) follow
  long multi-section instruction stacks less reliably — and those are the
  models council/cheap-mode runs use. No data yet on whether small models obey
  SCOPE/METHODOLOGY sections; worth a cheap A/B (run the same spec-driven issue
  with gpt-small and watch for stub-shipping).
- ⚠️ Some redundancy invites drift: WORKFLOW step 4 "Verify" overlaps
  END_TO_END; EFFICIENCY's "call finish() as soon as genuinely done" restates
  SCOPE's completion rule. Coherent today, but each future edit risks
  re-introducing contradiction. A consolidation pass (one COMPLETION section,
  one VERIFICATION section) would shrink tokens and drift surface.

## 5.3 The structural gap the prompts can't fix: nothing acts on council output

The single most interesting usage finding: in the PR #438 run, **all three
council reviewers independently caught the BT+EB methodology swap** — and the
pipeline did nothing with that. Delegate Stage 5 posts reviews; Stage 6 posts a
"revision plan" comment; no stage *acts*. The human had to notice by clicking
around the deployed app.

The council is currently the best defense against exactly the failure mode
that prompt-prose (#631-633) tries to prevent — but it's an open-loop defense.
Closing the loop (triage council findings → blocking vs. advisory → auto-run a
bounded revision resolve for blocking findings) would convert ~$1 of council
spend into an actual quality gate. This is a code feature, not a prompt fix,
and probably higher-leverage than any further prompt tuning.

## 5.4 Per-verb prompt reach — major caveat from Phase 2

Phase 2 found that the standalone `/agent-design` workflow job runs an inline
heredoc agent loop and **never adopted lib/design_loop.py**. Consequence: the
design-prompt improvements in #633 (verify file references, acceptance tests
for methodology claims), the gh tool, budget paragraph, retries, and cache
markers do NOT apply to production /agent-design — only to workshop/delegate
Stage 1, which do use the lib. So part of the prompt stack we think is deployed
is only deployed on some paths. Migrating the design job onto lib/design_loop.py
is a precondition for the prompt work to mean anything there.

## 5.5 Recommendations (ranked)

1. **Close the council loop** (code, not prompt): delegate Stage 6 triages
   council findings; blocking findings trigger one bounded revision pass.
   Highest leverage per dollar; directly targets methodology-fidelity.
2. **Migrate the /agent-design job to lib/design_loop.py** so the #633 prompt
   improvements (and caching — currently 0% hit rate there) actually deploy.
3. **Structural completion check** ("Stage 4½"): after resolve finishes a
   spec-driven run, a cheap model diffs spec-items vs. PR contents and posts a
   checklist; unchecked items block the "✅ complete" banner. Converts the
   stopping criterion from prose to procedure.
4. **Validate era-2 prompts empirically** on the next few real runs (iterations,
   cost, completeness vs. May baselines) before further prompt edits. Watch
   small-model compliance specifically.
5. **Consolidation pass on resolve's prompt stack** (merge overlapping
   sections; aim for ~30% token cut with zero semantic change). Bonus: smaller
   prompts are more model-agnostic.
6. **Don't re-add minimalism language.** Cache pricing changed the economics;
   the data shows exploration waste is bounded. If costs spike, fix with cache
   coverage (reconcile job currently runs cache-defeating settings — Phase 2)
   rather than with "don't read" prose.
