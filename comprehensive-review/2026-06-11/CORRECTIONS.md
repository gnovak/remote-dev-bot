# Corrections to the 2026-06-11 review

Discovered during the fix campaign; the findings files are preserved as
written, with errors noted here instead.

## Delegate Stage 6 is agentic, not advisory (§4.1, findings-prompts.md §5)

The review claims delegate Stage 6 "posts a 'revision plan' comment; no
stage *acts*" on council findings, and ranks "close the council loop" as
the highest-leverage feature on that basis.

**This was already false when the review was written.** PR #521
(`c13f7f8`, merged to dev 2026-04-11 and on main before the May usage
window) replaced the one-shot revision-plan call with an agentic Stage 6:
the workflow re-invokes `resolve.py` against the Stage 4 PR branch with
the Stage 5 council reviews, the revised design, and the revised spec
injected via `EXTRA_FILES`; the agent applies what it judges worthwhile
and commits to the same branch, bounded by `delegate_max_iterations` and
the watchdog timeout.

The error most likely came from `run_delegate`'s then-stale docstring
("6. Code revision plan — describes fixes"), which described the pre-#521
design. The docstring and two related comments were fixed alongside this
note.

Two review claims survive the correction:

- The BT-MM methodology catch on bridge-analysis PR #438 genuinely went
  unactioned — but that council was a manually invoked
  `/agent-review council=true`, a path that has no revision stage. The
  open loop is in standalone review (and build Stage 2), not delegate.
  Note `resolve.py` on a PR already ingests PR comments, so commenting
  `/agent-resolve` on a reviewed PR closes that loop manually today.
- Delegate's closed loop has essentially no production validation: the
  only May delegate run predates the #628/#631-633 prompt fixes. Code
  review of the Stage 6 step (2026-07-06) found the plumbing correct
  (env complete for resolve.py's `_require_env` set, wrapup consistent
  with the code budget, skip/timeout/cost-merge paths sane); it awaits a
  real run.
