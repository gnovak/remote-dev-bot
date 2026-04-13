# Design Workspace: Context & Cost Optimization

Working document for issue #496 — context trimming, tool call drops, caching.

## Status

**Phase: data gathering.** We're turning off existing token-saving measures to
get clean baseline runs, then deciding what to implement based on real data.

## Background

The dominant cost in long resolve runs is the rolling conversation history being
re-sent every iteration. With N iterations and ~m tokens per iteration:

- Total input tokens ~ N * prefix + 0.5 * m * N^2 (without trimming)
- Total input tokens ~ N * prefix + 20 * m * (N - 20) (with keep_n=20 trimming)

The key insight: **trimming tool results defeats caching, and caching is the
bigger lever.** If the message list is append-only, providers can cache the
entire conversation prefix — each iteration only pays for the newest turn.
Today, `trim_tool_results` rewrites assistant messages in the middle of history
every iteration, invalidating any cache beyond the static system prompt.

## Empirical data

### Run 24283767463 (Apr 11, remote-dev-bot self-dev, 31 iters)

- Model: claude-small (Sonnet 4.6), max_iterations=50, keep_n=20
- **697K input tokens, 7.3K output tokens, $1.78, 3 min**
- Trim fired 12 times (iterations 20-31), dropping 1 message per iter
- Steady-state context: 15-22K tokens per request
- Tool output sizes: mostly 80-8,100 chars (20-2,000 tokens)
- No single huge output — cost is from quadratic re-posting of small results
- Notable: 8 iterations were `sed -n` reads of files the agent already partially
  read earlier. Truncation at 8K forced multiple follow-up reads.

### Run 24174271003 (Apr 9, bridge-analysis, 63 iters)

- Model: claude-small (Sonnet 4.6), max_iterations=75, keep_n=20
- **993K input tokens, 12K output tokens, $2.05, 6 min**
- Similar pattern: small tool outputs, quadratic re-send is the bottleneck
- Estimated ~575 tokens per tool pair, steady-state ~17.5K per request

## Current token-saving measures (and assessment)

| # | Measure | Config key | Status | Assessment |
|---|---------|-----------|--------|------------|
| 1 | **Tool result trimming** | `context_keep_tool_results: 20` | Active | **Harmful.** Defeats caching by rewriting messages mid-history. Saves ~35% of tokens on a 63-iter run, but caching would save 70-80%. Also removes context the agent may need. |
| 2 | **Bash output truncation** | `bash_output_limit: 8000` | Active | **Probably harmful.** Forces agents into multi-iteration `sed -n` dances to reconstruct files they could have read in one call. The extra iterations cost more than the saved tokens, especially with caching. |
| 3 | **Context distillation** | `distill_enabled: true` | Active | **Helpful, keep.** One-time pre-pass, doesn't interact with caching. Reduces the static prefix by identifying relevant files. Saves ~$0.89 on a 63-iter run (312K tokens saved). |
| 4 | **Context compaction** | `max_context_tokens: 0` | Disabled | **Keep disabled.** Each compaction is an LLM call that also invalidates the cache. More useful as a quality lever (summarizing to keep model on track) than a cost lever. |
| 5 | **Smart drop ordering** | (in trim_tool_results) | Active | **Moot if we stop dropping.** Currently: drop read-only bash first, then file reads, then write results. |
| 6 | **Cache marker** | (single, on initial user msg) | Active | **Insufficient.** Only caches ~6K of static prefix. Need to advance markers to cover the conversation. |

## Plan: clean baseline runs

**Goal:** See the true tool output size distribution and context growth with no
artificial limits, so we can make data-driven decisions.

### Config changes for baseline runs

```yaml
agent:
  context_keep_tool_results: 0   # disable dropping entirely
  bash_output_limit: 0           # disable truncation entirely
  # distill_enabled: true        # keep — doesn't interact with caching
```

### What to measure

From the baseline runs, we want to know:
1. **Tool output size distribution.** Histogram of result sizes in chars/tokens.
   Are there outliers? What's the 95th percentile?
2. **Context growth curve.** How large does context get with no drops?
   Does it hit model limits on long runs?
3. **Iteration count delta.** Do agents need fewer iterations when they can
   read whole files? (Compare to historical runs on similar tasks.)
4. **Cache hit rate.** With append-only messages, what fraction of input is
   cached? (Read from LiteLLM response headers / usage.)

## Design ideas under consideration

### A. No drops + cache markers (primary proposal)

- Stop dropping tool results entirely. Append-only message list.
- Place cache markers at the conversation tail so the full prefix is cached.
- Safety valve: only drop if approaching model context limit (e.g., 80% of 200K).
- When forced to drop, drop largest results first, oldest within each size tier.

**Estimated savings:** 70-80% of input token cost on long runs.

### B. Short-TTL drops for large results only

- Keep small results forever (agent's working memory).
- Drop large results (above X chars) after K iterations (e.g., 5).
- Hypothesis: agent reads a big file dump, extracts what it needs in 1-2 iters,
  then the dump is dead weight.

**Status:** Interesting but possibly unnecessary if caching handles the re-send
cost. Large results that are cached cost very little to keep. Revisit after
baseline data.

### C. Raise/remove bash_output_limit

- Current: 8000 chars (first 4K + last 4K).
- Proposal: raise to 30-50K, or disable entirely (0).
- Removes the perverse incentive to do multiple `sed -n` reads.
- With caching, the extra tokens per read are affordable.

**Risk:** An accidental `cat` of a huge file could produce unbounded output.
Keep some limit as a safety net, but make it generous enough that agents rarely
hit it in normal use. 50K chars (~12.5K tokens) is probably right — large
enough for any reasonable file read, small enough to bound pathological cases.

### D. Line numbers in distillation and structural extract

- Add line numbers to file content in `format_codebase()` and
  `format_structural_extract()`.
- Distillation output can then say "relevant function at resolve.py:656-710".
- Agent can do `sed -n '656,710p'` on first iteration instead of exploratory
  grep-then-read dance.

**Status:** Orthogonal to caching. Reduces iteration count, which is the
biggest cost lever. Should implement regardless of caching approach.

### E. Line numbers in the file listing

- Currently `git ls-files` dumps bare paths.
- Adding line counts (e.g., `lib/resolve.py (1750 lines)`) could help agents
  decide whether to `cat` vs `sed -n`.

**Status:** Low effort, modest benefit. Nice to have.

## Open questions

1. **Anthropic cache markers vs automatic caching.** Does Anthropic's automatic
   prefix caching work without explicit `cache_control` markers? If so, just
   stopping drops might be sufficient with zero marker changes. Need to verify.

2. **OpenAI automatic prefix caching.** OpenAI caches identical prefixes
   automatically. With append-only messages this should just work. Verify with
   a GPT model run.

3. **Gemini caching behavior.** Gemini uses `cachedContent` API. Does LiteLLM
   translate `cache_control` markers correctly? Does it benefit from append-only?

4. **Context compaction as quality lever.** Even if we don't need it for cost,
   does summarizing old context help the agent stay focused on long runs? The
   63-iter bridge-analysis run had the agent re-reading the same files in the
   40s-50s iterations — possibly because it lost track of what it had already done.

## History

- **#478**: Token spend deep dive. Found that ~$10-11 of a $13.65 run went to
  uncached tool result re-sends.
- **#496**: This issue. Captured approaches A-D from the deep dive.
- **#498**: Added tool-result-size logging (`Tool: name(args) -> N chars`).
- **Context distillation**: Added ~Apr 2026. One-time pre-pass that extracts
  relevant files before the agent loop.
- **Tool result trimming**: Added ~Mar 2026 (`context_keep_tool_results`).
  Keeps last N tool pairs, drops oldest. Smart ordering: read-only bash first,
  file reads second, writes last.
- **Bash output truncation**: Added ~Mar 2026 (`bash_output_limit: 8000`).
  First 4K + last 4K chars of any bash output exceeding the limit.
- **Apr 12 analysis session**: Reviewed runs 24174271003 (63 iters, $2.05) and
  24283767463 (31 iters, $1.78). Concluded that per-pair sizes are small
  (~575 tokens), cost is dominated by quadratic re-posting, and caching is the
  primary lever. Tool call dropping is counterproductive because it defeats
  caching. Bash truncation is counterproductive because it forces extra
  iterations. Plan: disable both, get clean baseline runs, then implement
  caching properly.
