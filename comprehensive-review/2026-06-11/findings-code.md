# Comprehensive review (2026-06-11) — Phase 1: lib/ code

## lib/formatting.py (173 lines)
- [STALE] formatting.py:97 — docstring says "the bug fixed in this commit"; "this commit" is meaningless to readers of the file — should describe the fix, not the commit
- [NIT] formatting.py:11,40 — `_fmt_tok` uses uppercase 'K' (42.5K) while `_fmt_loc` uses lowercase 'k' (1.5k); inconsistent suffix casing between adjacent helpers
- [NIT] formatting.py:16,19 — `round(v)` uses banker's rounding (round(10.5M) → "10M"); cosmetic only

## lib/tools.py (219 lines)
- [SMELL] tools.py:41-44 — repo-bounds `abs_path.startswith(repo_root)` check is dead code: the `..`/absolute checks on line 34 already guarantee normpath stays under cwd; also classic prefix-match pattern (`/repo` matches `/repo-evil`) if it ever did fire
- [STALE] tools.py:25-27 — docstring says repo_bounds=False "instead checks that the path exists"; in fact the `..`/absolute rejection still applies in that mode too (line 34-38), so "instead" is misleading
- [NIT] tools.py:149 — `git grep -n --no-color pattern` without `-e`: a pattern starting with `-` is parsed as a flag and errors; `-e` before the pattern would fix
- [NIT] tools.py:55 — dangerous-pattern list misses `rm -fr /` variant (only `-rf` matched); best-effort blocklist, noting for completeness

## lib/context.py (463 lines)
- [BUG] context.py:330-337 — `compact_messages` cuts post-system messages at a raw index without respecting assistant(tool_calls)/tool pairing: if the boundary lands between an assistant tool_calls message (compacted) and its role="tool" results (kept in `remaining`), the new message list has orphaned tool results with no preceding tool_use — providers reject this with a 400. Affects resolve.py and reconcile.py compaction paths.
- [BUG-latent] context.py:279 — `for tc in msg.get("tool_calls", [])` raises TypeError if a message carries `tool_calls: None` (current callers never construct that, but raw litellm dicts do); `_build_tool_call_map` and `trim_tool_results` guard with truthiness, `estimate_tokens` doesn't — use `msg.get("tool_calls") or []`
- [STALE] context.py:149 — `trim_tool_results` docstring first line still says "Remove oldest tool call/result pairs"; the implementation drops individual tool results with read/write smart ordering, not whole pairs (the body text below describes the real policy; the summary line and AGENTS.md "drops the oldest pairs" description predate the smart-ordering rewrite)
- [NIT] context.py:31-37 — `classify_provider_error` regex `"([^"]+)"` truncates provider messages containing escaped quotes; cosmetic

## lib/config.py (771 lines)
- [BUG] config.py:714-717 — `extra_instructions` / `model_extra_instructions` are written to GITHUB_OUTPUT as bare `key=value` lines. The documented config format (remote-dev-bot.yaml:33 `extra_instructions: |`) is a multi-line block scalar; a multi-line value corrupts GITHUB_OUTPUT (needs the `key<<EOF` heredoc syntax) and fails the parse job ("Invalid format"). Any user who uncomments the shipped example with >1 line hits this.
- [STALE] config.py:57-62 — `normalize_config` docstring lists "mode.context_files: → mode.extra_files:" under "Renames performed", but the code raises ValueError on `context_files` (line 73) instead of renaming; only `additional_instructions` is actually renamed
- [SMELL] config.py:443-444 — `timeout_minutes` inline arg applied twice: already folded in at line 427 (`effective_timeout`), then re-applied at 443; redundant and makes precedence reasoning harder
- [SMELL] config.py:157 — `if not name or not value: continue` silently ignores malformed arg lines like `max_iterations =` (empty value); user gets no signal their override was dropped (contrast with the loud unknown-arg error at 160)
- [SMELL] config.py:539-543 — args are logged twice in resolve_config ("Runtime args" at 368 and "Command-line args" at 539); duplicate logging block
- [NIT] config.py:399 — agent config dict still named `oh` (OpenHands legacy) after the `openhands:` → `agent:` rename
- [NIT] config.py:222 — first-line regex makes trailing punctuation fail: `/agent-resolve.` parses command_part as "resolve." → "Unknown mode" error rather than tolerating it

## lib/cumulative_cost.py (253 lines)
- [SMELL] cumulative_cost.py:43 — prior-cost extraction sums every `**$X.XX**` in all comments, not just those inside `### 💰 Cost` tables; any unrelated bold dollar amount in an issue/PR comment (human or agent prose) silently inflates the cumulative total. The label-based anti-double-count scheme is documented but inherently fragile.
- [SMELL] cumulative_cost.py:135 — linked-issue detection regexes the concatenation of PR body + ALL comments for `Fixes #N`; a casual "Closes #N" in any discussion comment links (and double-counts) the wrong issue. Matching only the PR body would be safer.
- [NIT] cumulative_cost.py:92-112 — all gh failures silently swallowed (`except Exception: pass`); acceptable for a cosmetic table, but a one-line stderr note would aid debugging missing cumulative rows

## lib/post_fallback_cost.py (177 lines)
- [NIT] post_fallback_cost.py:47 — `_read_usage` catches FileNotFoundError/JSONDecodeError/ValueError but not TypeError; a malformed usage file with wrong value types (e.g. `"cost": {}`) crashes the fallback poster instead of degrading to zeros
- clean otherwise

## lib/generate_index.py (180 lines)
- [NIT] generate_index.py:120-127 — dataclass branch shows only fields; public methods on dataclasses are omitted from the index (plain classes get methods, dataclasses don't)
- [NIT] generate_index.py:88-90 — `AsyncFunctionDef` is rendered as `def` rather than `async def`
- clean otherwise

## lib/distill.py (650 lines)
- [BUG] distill.py:296-298 — `ast.get_source_segment(source, node.args)` ALWAYS returns None: `ast.arguments` nodes carry no position attributes (verified empirically). The "real signature" path in `_format_function_sig` is dead; every signature comes from the fallback at line 302, which emits only positional arg names — defaults, `*args`, keyword-only args, `**kwargs`, and annotations are silently dropped from every structural extract. Fix: `ast.unparse(node.args)` or get_source_segment on the FunctionDef and slice.
- [SMELL] distill.py:131-134 — glob-pattern handling for SKIP_DIRS entries starting with "*" is dead code: no entry in SKIP_DIRS (line 79) starts with "*"; the "*.egg-info" comment references a pattern that was never added
- [STALE] distill.py:151 — `_truncate_content` docstring says "Truncate content to cap characters" but it truncates to 2×half_chars (4K for source files), not to cap (50K); a 50,001-char file collapses to ~4K while a 50,000-char one is kept whole — surprising cliff worth a comment if intentional
- [SMELL] distill.py:288 — `_extract_python_signatures` returns a str normally but a LIST on the empty-parts fallback; the caller compensates with an isinstance check (line 319) — inconsistent return type
- [NIT] distill.py:337-349 — Tier-1/Tier-2 distill prompt hard-requires "COMPLETE file content verbatim", but gathered files above the cap were already truncated to ~4K (marked truncated="true"); the model is instructed to do something its input makes impossible for large files

## lib/design_loop.py (512 lines)
- [BUG] design_loop.py:421 (also resolve.py:1632, reconcile.py:598) — cache-write tracking reads `getattr(prompt_details, "cache_creation_input_tokens", 0)`, but litellm's PromptTokensDetailsWrapper field is named `cache_creation_tokens` (verified against installed litellm 1.83.7: getattr returns MISSING). cache_creation_tokens is therefore ALWAYS 0 in all three loops — "tokens written to cache" never appears in status logs, and build_cache_savings_summary never subtracts write overhead (savings overstated). `cached_tokens` (reads) is correct.
- [DRIFT] design_loop.py:437 — serializes tool calls with deprecated pydantic v1 `tc.dict()`; resolve.py:1705 uses `tc.model_dump()`. Same operation, two idioms; dict() emits DeprecationWarning and will break on a future pydantic
- [STALE] design_loop.py:448-451 — per-tool logging has branches for "bash" and "finish" tools that don't exist in this loop's TOOLS (copied from resolve); dead branches
- [STALE] design_loop.py:312-322 — run_design_loop docstring's "Returns" list omits cache_read_tokens / cache_creation_tokens, which are in the returned dict
- [DRIFT] design_loop.py — no moving-tail cache_control marker: resolve.py:1355 and reconcile.py:483 both place the moving-tail prompt-cache marker on the last message; design_loop (and workshop Stage 1/3 through it) never sets cache_control, so multi-iteration design runs on Anthropic models pay full input price every iteration. If intentional (short loops), deserves a comment; looks like the fix landed in resolve/reconcile and never propagated.

## lib/reconcile.py (849 lines)
- [BUG] reconcile.py:607-611,788-791 — the "No tool calls for 3 consecutive iterations" break writes NO status, but the post-loop logic assumes any non-natural loop exit "wrote a more specific status" (comment at 479-481). After this break, finish_args is None and loop_completed_naturally is False, so write_status is never called — /tmp/resolve_status.json is missing/stale and the workflow reports nothing useful. (The fix in 2faf5b0 covered exception breaks but missed this break.)
- [BUG] reconcile.py:298-300 — conflict-side explanation in RECONCILE_WORKFLOW is wrong for rebase: during `git rebase origin/BASE`, the side ABOVE `=======` (HEAD/ours) is origin/BASE and the side BELOW (theirs/incoming) is the PR branch's commit being replayed. The prompt says the INCOMING side below `=======` is "from origin/{BASE_BRANCH}" — backwards; primes the agent to misattribute intent on every conflict.
- [DRIFT] reconcile.py:546 — calls bare `completion()` with no transient-error retry; design_loop.py:404 wraps via `completion_with_retries` (and resolve.py does too). A single Anthropic "overloaded" 529 kills a reconcile run that the siblings would survive. (ServiceUnavailableError lands in the generic APIError handler → fatal break.)
- [DRIFT] reconcile.py:494 vs design_loop.py:477 — wrapup-injection condition uses `==` (exact iteration) here but `>=` in design_loop; functionally similar given the injected-once flag, but the sibling logic has quietly diverged in shape
- [SMELL] reconcile.py:384-403 — system prompt contains TWO iteration-budget sections when wrapup is enabled ("## Iteration Budget" from budget_paragraph plus "## Iteration Budget — WRAP-UP REQUIRED" from wrapup_hint), stating the budget twice with different framing
- [NIT] reconcile.py:417 — `open('/tmp/agent_start_sha','w').write(...)` without close/with-block
- [NIT] reconcile.py:764 — `last_iteration + 1` reports 1 iteration even when MAX_ITERATIONS=0 and the loop never ran

## lib/resolve.py (2167 lines)
- [BUG] resolve.py:1523-1567 — exception handler order makes the ContextWindowExceededError recovery DEAD CODE: litellm's ContextWindowExceededError subclasses BadRequestError (verified: CWE → BadRequestError → openai.BadRequestError), and `except BadRequestError` at 1523 precedes `except ContextWindowExceededError` at 1544. A context overflow is caught by the BadRequest handler → run breaks with "Bad request at iteration N" instead of force-trimming and gracefully wrapping up. Move the CWE handler above BadRequestError.
- [BUG] resolve.py:1657-1659,1681-1682,1983-1989 — same status-file gap as reconcile: the "no tool calls for 3 consecutive iterations" break (both empty-choices and no-tool-calls variants) writes NO status, but the finish_args-is-None path only writes status when loop_completed_naturally — so /tmp/resolve_status.json is never written for this exit path.
- [BUG] resolve.py:1104-1111 — `create_pr` escapes only double quotes in pr_title, then interpolates into a shell=True command: backticks, `$(...)`, and `\` inside double quotes remain live. pr_title is LLM-authored from untrusted issue text — a prompt-injected title like `$(curl ...)` executes in the runner. Use a list argv (no shell) or shlex.quote.
- [DRIFT] resolve.py:1002-1076 — resolve has its own LOCAL `trim_tool_results`, a stale copy of the pre-smart-ordering implementation (drops oldest results regardless of read/write kind). The read/write-aware version lives in lib/context.py and is used by reconcile and design_loop. Ironically resolve — the only loop that writes code — is the one that lost the "protect write results" behavior. Local copy also lacks context.py's updated drop-policy docs.
- [DRIFT] resolve.py:1407 vs reconcile.py:494 vs design_loop.py:473 — three different wrapup-injection mechanics: resolve re-injects EVERY iteration past the threshold (no injected-once flag), reconcile injects exactly once (==), design_loop injects once via flag (>=). If resolve's repeated nagging is intentional escalation, the siblings' once-only behavior (or the divergence) deserves a comment.
- [DRIFT] reconcile.py — has no ContextWindowExceededError / context-overflow recovery at all, while resolve has (intended) trim-and-wrap-up handling; long reconciles with big conflicts can overflow and die with a generic "API error"
- [STALE] resolve.py:54 — COMMIT_TRAILER env var is read but never used anywhere (config.py:24 says commit_trailer was removed); dead env plumbing
- [SMELL] resolve.py:742 — GIT_INSTRUCTIONS is a plain (non-f) string, so the agent literally sees "Must include `Fixes #{ISSUE_NUMBER}` on its own line"; models usually interpret it, but the unformatted placeholder is fragile (the finish-tool description does it right with 'Fixes #N (where N is the issue number)')
- [NIT] resolve.py:1157 — build_cost_table fallback base ref hardcodes `origin/main` ("$(git merge-base HEAD origin/main)") instead of TARGET_BRANCH; wrong LOC metrics for dev-targeting repos when /tmp/agent_start_sha is missing
- [NIT] resolve.py:2048 — pr_title fallback "Fix for issue #N" is exactly the pattern the system prompt forbids ("Bad: Fix issue #44")
- [NIT] resolve.py:2099 — `open("/tmp/cost_embedded","w").write(...)` without close/with-block (same idiom as reconcile.py:417)

## lib/workshop.py (1710 lines)
- [BUG] workshop.py:1379-1400 vs 1644-1649 — inconsistent /agent-command blocking in delegate: Stage 3c nulls the artifact (`revised_spec = None`) when the revision contains an /agent command, but Stage 3 only suppresses the POST — the contaminated `revised_design` is still returned, fed to Stage 3a as context, and passed to the Stage 4 resolve job. The "blocked for safety" message is cosmetic for Stage 3.
- [BUG] workshop.py — distillation cost is dropped from all workshop/delegate totals: run_design_loop returns distill_input_tokens/distill_output_tokens/distill_cost separately from input_tokens/cost, and run_workshop (846-854) and run_delegate (1200-1202, 1447-1449) sum only the loop fields. resolve.py seeds its totals with distill+linked-issue cost; workshop/delegate under-report every Stage 1/3a run's real cost.
- [DRIFT] workshop.py:752 — nested f-string `f'`{m['alias']}`'` with same-quote reuse requires Python 3.12+ (PEP 701); the three sibling call sites (459, 1264, 1515) use 3.x-safe `'`' + m['alias'] + '`'` concatenation. Works on current runners but breaks py_compile on ≤3.11 and is a copy-paste landmine.
- [SMELL] workshop.py:103-107 — `_PROVIDER_KEY_MAP` duplicates config.py's KNOWN_PROVIDERS; the AGENTS.md "adding a provider" checklist doesn't mention this third copy, so a new provider's council members would be silently skipped ("API key not configured")
- [NIT] workshop.py:1210-1220 — first early-return dict from run_delegate omits the `design_analysis` / `revision_result` / `spec_revision_result` keys that the other returns include; consumers must use .get

## lib/feedback.py (476 lines)
- [SMELL] feedback.py:388,463 — report_problems / get_consent_prompt call get_environment_info() fresh instead of using the InstallReport's own os_info/shell/python_version fields; the dataclass's auto-collected (and caller-overridable) env fields are only used by to_dict(), so a customized report still posts the live-environment values
- [NIT] feedback.py:275,336,354 — gh subprocess calls catch CalledProcessError but not FileNotFoundError; a missing gh binary raises instead of returning the documented None/False/[] failure values
- clean otherwise

## tests/ skim (staleness only)
- [STALE] tests cover `lib.context.trim_tool_results` (test_context.py, incl. read/write smart-ordering) but NOT resolve.py's stale local copy — the function resolve actually runs is untested, and the suite green-lights behavior resolve doesn't have
- [STALE] test_cache_distill_savings.py exercises the formatting side with synthetic usage files, so it cannot catch the upstream cache_creation_tokens-always-0 extraction bug (wrong attribute name in all three loops)
- test docstrings otherwise current: legacy-key tests (openhands:/context_files:) correctly assert the raise behavior; test_no_op/test_reconcile/test_resolve_recovery import-time-env patterns documented and accurate; no references to removed features found

## Top findings (Phase 1)
1. [BUG] resolve.py:1523 — ContextWindowExceededError recovery is dead code: it subclasses BadRequestError, whose handler comes first. Context overflow kills runs (status "Bad request") instead of trim-and-wrap-up. One-line fix: reorder handlers.
2. [BUG] resolve.py:1632 / reconcile.py:598 / design_loop.py:421 — cache-write tokens read from a nonexistent attribute (`cache_creation_input_tokens` vs litellm's `cache_creation_tokens`); always 0, so cache savings are overstated and write costs invisible in every status log.
3. [BUG] resolve.py:1104 — pr_title shell injection: LLM-authored title interpolated into shell=True `gh pr create` with only double-quote escaping; `$(...)`/backticks execute on the runner. Reachable via prompt injection from untrusted issue text.
4. [BUG] config.py:714 — multi-line `extra_instructions` (the documented `|` block-scalar format) corrupts GITHUB_OUTPUT; the shipped config example, if uncommented, breaks the parse job.
5. [DRIFT] resolve.py:1002 — resolve runs a stale local `trim_tool_results` without the read/write-aware drop ordering that context.py provides to reconcile/design_loop; the code-writing loop is the one missing the protect-write-results fix, and tests only cover the context.py version.
6. [BUG] resolve.py:1657/reconcile.py:609 — the "no tool calls ×3" break writes no status file, and the post-loop logic assumes a status was already written; the run ends with no failure explanation.
7. [BUG] reconcile.py:298 — rebase conflict-marker sides described backwards in the system prompt (says below-`=======` comes from origin/BASE; it's the PR commit), priming the agent to misattribute intent on every conflict.
8. [BUG] workshop.py:1379 — delegate Stage 3 only blocks POSTING a design containing /agent commands; the contaminated design still flows to Stages 3a/4 (Stage 3c nulls it correctly — inconsistent).
9. [BUG] distill.py:296 — `ast.get_source_segment` on ast.arguments always returns None; every structural-extract signature silently degrades to positional arg names only (no defaults/kwonly/annotations).
10. [DRIFT] design_loop.py — no moving-tail cache_control marker (resolve/reconcile both have it); design/workshop/delegate exploration stages on Anthropic models forgo prompt caching entirely. Also workshop/delegate totals drop distillation cost.
