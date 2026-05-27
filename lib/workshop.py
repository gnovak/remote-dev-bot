"""Workshop mode: multi-model design council with human checkpoints.

MVP scope: Stages 1 (design) and 2 (council review).

Stage 1 — Design: Run the agentic design loop (same as /agent-design) using
the configured default model.

Stage 2 — Council review: Each council model posts a structured peer critique
of the Stage 1 design. Council reviews run simultaneously (not sequentially)
so critiques are maximally independent.

After Stage 2, the bot posts a summary comment and stops. Human reviews the
critiques, then decides to call `/agent-design` for a revised proposal or
`/agent-resolve` to implement directly.
"""

import math
import os
import re
import sys
import time

# Ensure sibling modules are importable when run from the workflow
sys.path.insert(0, os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# Cost formatting helpers — imported from shared lib/formatting.py
# ---------------------------------------------------------------------------

from formatting import _fmt_tok, _fmt_ela, _fmt_bpd, _fmt_loc, _fmt_info, TABLE_HEADER


def _build_cost_table(input_tokens, output_tokens, cost, elapsed, output_text):
    rounded = math.ceil(cost * 100) / 100
    rows = [('Time', _fmt_ela(elapsed))]
    _info = _fmt_info(output_text)
    if _info:
        rows.append(('Info', _info))
    rows += [
        ('Input', _fmt_tok(input_tokens) + ' tokens'),
        ('Output', _fmt_tok(output_tokens) + ' tokens'),
        ('Info/$', _fmt_bpd(output_text, cost)),
        ('**Cost**', f'**${rounded:.2f}**'),
    ]
    lines = ['---', '', '### 💰 Cost', '', '| Metric | Value |', '|--------|-------|']
    lines += [f'| {k} | {v} |' for k, v in rows]
    return '\n'.join(lines)


def _build_stage_cost_block(
    *,
    github_repo,
    issue_number,
    input_tokens,
    output_tokens,
    cost,
    elapsed,
    output_text,
):
    """Build the per-step cost table for a delegate stage, followed by the
    canonical cumulative cost table (only when there are prior cost markers
    on the issue — i.e., this is not the first step to emit a cost block).

    The cumulative table is produced by lib/cumulative_cost.compute_cumulative_table,
    which is the same code paths individual /agent-resolve / /agent-design /
    /agent-review invocations use, so a delegate run looks identical to the
    sequence of manual invocations it expands into.
    """
    parts = [_build_cost_table(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        elapsed=elapsed,
        output_text=output_text,
    )]
    if github_repo and issue_number:
        try:
            from cumulative_cost import compute_cumulative_table
            cum = compute_cumulative_table(
                repo=github_repo,
                number=str(issue_number),
                current_cost=cost,
                current_input_tokens=input_tokens,
                current_output_tokens=output_tokens,
            )
            if cum:
                parts.append('')
                parts.append(cum)
        except Exception as e:
            # Cumulative-cost computation is best-effort visibility — never
            # block a stage from posting its result if it fails.
            import sys as _sys
            print(f"  [delegate] Could not compute cumulative cost: {e}", file=_sys.stderr)
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------

# Map from model ID prefix to environment variable name
_PROVIDER_KEY_MAP = {
    'anthropic/': 'ANTHROPIC_API_KEY',
    'openai/': 'OPENAI_API_KEY',
    'gemini/': 'GEMINI_API_KEY',
}


def _get_required_api_key_name(model_id):
    """Return the env var name required for model_id, or None if unknown."""
    for prefix, key_name in _PROVIDER_KEY_MAP.items():
        if model_id.startswith(prefix):
            return key_name
    return None


# ---------------------------------------------------------------------------
# Council review prompt
# ---------------------------------------------------------------------------

COUNCIL_REVIEW_SYSTEM_PROMPT = (
    "You are a senior software architect participating in a design review council. "
    "You have been given a design proposal for a GitHub issue and must provide a "
    "structured critique.\n\n"
    "Your review should be thorough but constructive. Focus on:\n"
    "- Technical correctness and feasibility\n"
    "- Potential blind spots or edge cases\n"
    "- Alternative approaches that might be simpler or more robust\n"
    "- Open questions that need resolution before implementation\n\n"
    "Be specific and actionable in your feedback. Reference specific parts of the "
    "design when raising concerns."
)

COUNCIL_REVIEW_FORMAT = """\
Format your response EXACTLY as follows (use these exact headers):

## Design Review by {model_alias}

**What I'd keep:** …

**Concerns:** …

**Alternatives worth considering:** …

**Open questions for the author:** …
"""


def build_council_review_prompt(
    *,
    issue_title,
    issue_body,
    issue_comments,
    design_analysis,
    model_alias,
):
    """Build the user prompt for a council review."""
    return (
        f"## Issue: {issue_title}\n\n"
        f"{issue_body}\n\n"
        f"## Discussion:\n{issue_comments}\n\n"
        f"## Design Proposal (to review):\n\n{design_analysis}\n\n"
        f"---\n\n"
        f"Please review the design proposal above and provide your critique.\n\n"
        f"{COUNCIL_REVIEW_FORMAT.format(model_alias=model_alias)}"
    )


# ---------------------------------------------------------------------------
# Single council review call (non-agentic)
# ---------------------------------------------------------------------------

def run_council_review(
    *,
    model_id,
    model_alias,
    issue_title,
    issue_body,
    issue_comments,
    design_analysis,
    extra_instructions="",
    api_keys=None,
    system_prompt_override=None,
    user_content_override=None,
):
    """Run a single council review (non-agentic single LLM call).

    Parameters
    ----------
    model_id : str
        LiteLLM model identifier (e.g. "anthropic/claude-sonnet-4-20250514").
    model_alias : str
        Human-readable alias for the model (e.g. "claude-small").
    issue_title, issue_body, issue_comments : str
        Issue context.
    design_analysis : str
        The Stage 1 design analysis to review. Ignored if user_content_override
        is provided.
    extra_instructions : str
        Additional instructions appended to the council reviewer system prompt.
        Should be the combination of mode-level and model-level extra_instructions.
    api_keys : dict or None
        Optional mapping of env var names to values to set before the call.
    system_prompt_override : str or None
        If provided, used as the base system prompt instead of COUNCIL_REVIEW_SYSTEM_PROMPT.
        Useful for reusing this function for spec reviews.
    user_content_override : str or None
        If provided, used as the user message instead of building from the
        design review template. Useful for reusing this function for spec reviews.

    Returns
    -------
    dict with keys:
        - review: str — the review text
        - model_alias: str
        - model_id: str
        - input_tokens: int
        - output_tokens: int
        - cost: float
    """
    from litellm import completion as litellm_completion
    from context import completion_with_retries

    # Set API keys if provided
    if api_keys:
        for key, value in api_keys.items():
            if value:
                os.environ[key] = value

    if user_content_override is not None:
        user_content = user_content_override
    else:
        user_content = build_council_review_prompt(
            issue_title=issue_title,
            issue_body=issue_body,
            issue_comments=issue_comments,
            design_analysis=design_analysis,
            model_alias=model_alias,
        )

    system_prompt = system_prompt_override if system_prompt_override is not None else COUNCIL_REVIEW_SYSTEM_PROMPT
    if extra_instructions:
        system_prompt += "\n\n" + extra_instructions

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    response = completion_with_retries(
        litellm_completion,
        model=model_id,
        messages=messages,
        max_tokens=8192,
    )

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = getattr(response, "_hidden_params", {}).get("response_cost", None) or 0.0

    review_text = response.choices[0].message.content or ""

    return {
        "review": review_text,
        "model_alias": model_alias,
        "model_id": model_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
    }


# ---------------------------------------------------------------------------
# Council code review (build mode Stage 2)
# ---------------------------------------------------------------------------

COUNCIL_CODE_REVIEW_SYSTEM_PROMPT = (
    "You are a senior software engineer participating in a code review council. "
    "You have been given a pull request that resolves a GitHub issue, and you "
    "must provide a structured code review.\n\n"
    "Your review should be thorough but constructive. Focus on:\n"
    "- Correctness: does this actually solve the issue? Any edge cases missed?\n"
    "- Code quality: readability, maintainability, appropriate abstractions\n"
    "- Potential bugs or regressions introduced by the change\n"
    "- Alternative approaches that might be simpler or more robust\n\n"
    "Be specific and actionable. Reference file names when raising concerns. "
    "If the change looks good overall, say so clearly — do not manufacture concerns."
)

COUNCIL_CODE_REVIEW_FORMAT = """\
Format your response EXACTLY as follows (use these exact headers):

## Code Review by {model_alias}

**Overall:** [LGTM / Looks good with minor comments / Needs changes]

**What I'd approve:** …

**Concerns:** …

**Suggestions:** …

**Questions for the author:** …
"""


def build_council_code_review_prompt(
    *,
    issue_title,
    issue_body,
    pr_title,
    pr_body,
    pr_diff,
    model_alias,
):
    """Build the user prompt for a council code review."""
    return (
        f"## Issue being resolved: {issue_title}\n\n"
        f"{issue_body}\n\n"
        f"## Pull Request: {pr_title}\n\n"
        f"{pr_body}\n\n"
        f"## Diff:\n\n```diff\n{pr_diff}\n```\n\n"
        f"---\n\n"
        f"Please review the pull request above and provide your code review.\n\n"
        f"{COUNCIL_CODE_REVIEW_FORMAT.format(model_alias=model_alias)}"
    )


def run_council_code_review(
    *,
    model_id,
    model_alias,
    issue_title,
    issue_body,
    pr_title,
    pr_body,
    pr_diff,
    extra_instructions="",
    api_keys=None,
):
    """Run a single council code review (non-agentic single LLM call).

    Returns dict with keys: review, model_alias, model_id,
    input_tokens, output_tokens, cost.
    """
    from litellm import completion as litellm_completion
    from context import completion_with_retries

    if api_keys:
        for key, value in api_keys.items():
            if value:
                os.environ[key] = value

    user_content = build_council_code_review_prompt(
        issue_title=issue_title,
        issue_body=issue_body,
        pr_title=pr_title,
        pr_body=pr_body,
        pr_diff=pr_diff,
        model_alias=model_alias,
    )

    system_prompt = COUNCIL_CODE_REVIEW_SYSTEM_PROMPT
    if extra_instructions:
        system_prompt += "\n\n" + extra_instructions

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    response = completion_with_retries(
        litellm_completion,
        model=model_id,
        messages=messages,
        max_tokens=8192,
    )

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = getattr(response, "_hidden_params", {}).get("response_cost", None) or 0.0

    review_text = response.choices[0].message.content or ""

    return {
        "review": review_text,
        "model_alias": model_alias,
        "model_id": model_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
    }


def run_build_council(
    *,
    council_models,
    issue_title,
    issue_body,
    pr_title,
    pr_body,
    pr_diff,
    extra_instructions="",
    post_comment_fn=None,
    banner_label="Build Stage 2 — Council Code Review",
    attribution_label="/agent-build Stage 2",
    completion_label="Build Stage 2 complete — awaiting human review",
):
    """Run parallel council code reviews on a PR.

    Used by:
      - /agent-build Stage 2 (defaults)
      - /agent-delegate Stage 5 (overrides labels for "Delegate Stage 5/6")
      - /agent-review with council=true (overrides labels for plain
        "Council Code Review", no build/delegate prefix)

    Runs each council model's review in parallel (non-agentic). Posts each
    review via post_comment_fn (defaults to print if None).

    extra_instructions is the mode-level extra_instructions string; each council
    member's model-level extra_instructions (from council_model["extra_instructions"])
    is appended per-reviewer.

    banner_label, attribution_label, completion_label parameterize the
    user-visible mode-specific text so the same parallel-review code can
    serve build mode, delegate Stage 5, and /agent-review council=true
    without each emitting "Build Stage 2 — ..." headers.

    Returns dict with council_results, total_input_tokens,
    total_output_tokens, total_cost.
    """
    import concurrent.futures
    from design_loop import has_agent_command

    def post(body):
        if post_comment_fn:
            post_comment_fn(body)
        else:
            print(body)

    if not council_models:
        post(
            f"## 🏛️ {banner_label}\n\n"
            f"⚠️ No council models configured. Skipping council code review.\n"
        )
        return {
            "council_results": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
        }

    post(
        f"## 🏛️ {banner_label}\n\n"
        f"Requesting code reviews from {len(council_models)} council member(s): "
        f"{', '.join('`' + m['alias'] + '`' for m in council_models)}...\n"
    )

    council_results = []

    def _run_single_code_review(council_model):
        model_id = council_model["id"]
        key_name = _get_required_api_key_name(model_id)
        if key_name is not None:
            key_value = os.environ.get(key_name, "")
            if not key_value:
                print(
                    f"Skipping {council_model['alias']} — API key not configured "
                    f"({key_name} is empty or missing)",
                    flush=True,
                )
                return None

        # Combine mode-level and model-level extra_instructions for this reviewer
        model_extra = council_model.get("extra_instructions", "")
        reviewer_extra = "\n\n".join(p for p in [extra_instructions, model_extra] if p)

        review_start = time.time()
        result = run_council_code_review(
            model_id=model_id,
            model_alias=council_model["alias"],
            issue_title=issue_title,
            issue_body=issue_body,
            pr_title=pr_title,
            pr_body=pr_body,
            pr_diff=pr_diff,
            extra_instructions=reviewer_extra,
        )
        result["elapsed"] = time.time() - review_start
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(council_models)) as executor:
        futures = {
            executor.submit(_run_single_code_review, cm): cm
            for cm in council_models
        }
        for future in concurrent.futures.as_completed(futures):
            cm = futures[future]
            try:
                result = future.result()
                if result is None:
                    continue
                council_results.append(result)
            except Exception as e:
                council_results.append({
                    "review": f"⚠️ Error during review: {e}",
                    "model_alias": cm["alias"],
                    "model_id": cm["id"],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "elapsed": 0.0,
                })

    for cr in council_results:
        if has_agent_command(cr["review"]):
            post(
                f"⚠️ **Agent loop blocked!** Review from `{cr['model_alias']}` "
                f"contained `/agent` command(s). Blocked for safety."
            )
        else:
            post(
                f"🤖 **Council reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                f"{cr['review']}\n\n"
                f"---\n"
                f"_Council code review by `{attribution_label}` (`{cr['model_alias']}`)_"
            )

    n = len(council_results)
    post(
        f"## {completion_label}\n\n"
        f"{n} model(s) have posted code reviews above. Please review the feedback "
        f"and address any concerns before merging.\n"
    )

    total_input = sum(cr.get("input_tokens", 0) for cr in council_results)
    total_output = sum(cr.get("output_tokens", 0) for cr in council_results)
    total_cost = sum(cr.get("cost", 0.0) for cr in council_results)

    return {
        "council_results": council_results,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost": total_cost,
    }


# ---------------------------------------------------------------------------
# Council filtering
# ---------------------------------------------------------------------------

def resolve_council_models(models, design_alias, council_config=None):
    """Resolve the list of council models.

    Parameters
    ----------
    models : dict
        All configured models (alias -> {"id": ...}).
    design_alias : str
        The alias of the design model.  Included in the default council so
        it can critique its own work in a critic role.
    council_config : list or None
        Explicit council list from mode config. If empty/None, defaults to
        all configured models (including the design model).

    Returns
    -------
    list of dict, each with "alias" and "id" keys.
    """
    council_models = []

    if council_config:
        # Explicit council list — use exactly what's specified
        for alias in council_config:
            if alias in models:
                council_models.append({
                    "alias": alias,
                    "id": models[alias]["id"],
                })
    else:
        # Default: all configured models (design model included — self-review
        # in a critic role is valuable)
        for alias, cfg in models.items():
            council_models.append({
                "alias": alias,
                "id": cfg["id"],
            })

    return council_models


# ---------------------------------------------------------------------------
# Workshop orchestration (Stages 1 and 2)
# ---------------------------------------------------------------------------

def run_workshop(
    *,
    model,
    model_alias,
    council_models,
    issue_title,
    issue_body,
    issue_comments="",
    extra_instructions="",
    council_extra_instructions="",
    extra_context="",
    max_iterations=10,
    wrapup_enabled=True,
    wrapup_iteration=0,
    context_keep_tool_results=0,
    post_comment_fn=None,
    distill_enabled=True,
):
    """Run the full workshop MVP (Stages 1 and 2).

    Parameters
    ----------
    model : str
        LiteLLM model ID for the design stage.
    model_alias : str
        Human-readable alias for the design model.
    council_models : list of dict
        Each dict has "alias", "id", and optionally "extra_instructions" keys.
    issue_title, issue_body, issue_comments : str
        Issue context.
    extra_instructions : str
        Additional instructions for the Stage 1 design agent (mode + model combined).
    council_extra_instructions : str
        Mode-level extra_instructions for council reviewers (Stage 2). Each
        reviewer's model-level extra_instructions is appended per-reviewer.
    extra_context : str
        Additional context for the design loop.
    max_iterations : int
        Max iterations for Stage 1 design loop.
    wrapup_enabled : bool
        Whether graceful wrapup is enabled.
    wrapup_iteration : int
        Iteration at which to inject wrapup message.
    context_keep_tool_results : int
        Number of recent tool results to keep.
    post_comment_fn : callable or None
        Function to post a comment: post_comment_fn(body: str) -> None.
        If None, comments are printed to stdout.

    Returns
    -------
    dict with keys:
        - design_result: dict from run_design_loop
        - council_results: list of dicts from run_council_review
        - total_input_tokens: int
        - total_output_tokens: int
        - total_cost: float
    """
    from design_loop import run_design_loop, has_agent_command

    def post(body):
        if post_comment_fn:
            post_comment_fn(body)
        else:
            print(body)

    # --- Stage 1: Design ---
    post(
        f"## 🔨 Workshop Stage 1 — Design\n\n"
        f"Running design exploration with `{model_alias}` (`{model}`)...\n"
    )

    design_start = time.time()
    design_result = run_design_loop(
        model=model,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_comments=issue_comments,
        extra_instructions=extra_instructions,
        extra_context=extra_context,
        max_iterations=max_iterations,
        wrapup_enabled=wrapup_enabled,
        wrapup_iteration=wrapup_iteration,
        context_keep_tool_results=context_keep_tool_results,
        distill_enabled=distill_enabled,
    )
    design_elapsed = time.time() - design_start

    design_analysis = design_result.get("analysis", "")

    if not design_analysis:
        post(
            f"⚠️ **Workshop Stage 1 did not produce an analysis.** "
            f"The design agent may have exhausted all iterations without "
            f"calling `submit_analysis`."
        )
        return {
            "design_result": design_result,
            "council_results": [],
            "total_input_tokens": design_result.get("input_tokens", 0),
            "total_output_tokens": design_result.get("output_tokens", 0),
            "total_cost": design_result.get("cost", 0.0),
        }

    # Check for agent command loop
    if has_agent_command(design_analysis):
        post(
            "⚠️ **Agent loop blocked!** The design analysis contained "
            "`/agent` command(s). The response has been blocked for safety."
        )
        return {
            "design_result": design_result,
            "council_results": [],
            "total_input_tokens": design_result.get("input_tokens", 0),
            "total_output_tokens": design_result.get("output_tokens", 0),
            "total_cost": design_result.get("cost", 0.0),
        }

    # Post design analysis with embedded cost table
    design_cost_table = _build_cost_table(
        input_tokens=design_result.get("input_tokens", 0),
        output_tokens=design_result.get("output_tokens", 0),
        cost=design_result.get("cost", 0.0),
        elapsed=design_elapsed,
        output_text=design_analysis,
    )
    post(
        f"🤖 **Model:** `{model_alias}` (`{model}`)\n\n"
        f"{design_analysis}\n\n"
        f"---\n"
        f"_Design analysis by `/agent-workshop` Stage 1 (`{model_alias}`)_\n\n"
        f"{design_cost_table}"
    )

    # --- Stage 2: Council Review ---
    if not council_models:
        post(
            "## 🏛️ Workshop Stage 2 — Council Review\n\n"
            "⚠️ No council models configured. Skipping council review.\n\n"
            "## Workshop complete\n\n"
            "The design proposal is above. No council review was performed."
        )
        return {
            "design_result": design_result,
            "council_results": [],
            "total_input_tokens": design_result.get("input_tokens", 0),
            "total_output_tokens": design_result.get("output_tokens", 0),
            "total_cost": design_result.get("cost", 0.0),
        }

    post(
        f"## 🏛️ Workshop Stage 2 — Council Review\n\n"
        f"Requesting critiques from {len(council_models)} council member(s): "
        f"{', '.join(f'`{m['alias']}`' for m in council_models)}...\n"
    )

    # Run council reviews simultaneously using ThreadPoolExecutor
    # Each review is a single non-agentic LLM call, so they're I/O-bound
    # and benefit from concurrent execution.
    import concurrent.futures

    council_results = []

    def _run_single_review(council_model):
        # Check if the required API key is available before attempting the call.
        model_id = council_model["id"]
        key_name = _get_required_api_key_name(model_id)
        if key_name is not None:
            key_value = os.environ.get(key_name, "")
            if not key_value:
                print(
                    f"Skipping {council_model['alias']} — API key not configured "
                    f"({key_name} is empty or missing)",
                    flush=True,
                )
                return None  # Signal skip

        # Combine mode-level and model-level extra_instructions for this reviewer
        model_extra = council_model.get("extra_instructions", "")
        reviewer_extra = "\n\n".join(p for p in [council_extra_instructions, model_extra] if p)

        review_start = time.time()
        result = run_council_review(
            model_id=model_id,
            model_alias=council_model["alias"],
            issue_title=issue_title,
            issue_body=issue_body,
            issue_comments=issue_comments,
            design_analysis=design_analysis,
            extra_instructions=reviewer_extra,
        )
        result["elapsed"] = time.time() - review_start
        return result

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(council_models)
    ) as executor:
        futures = {
            executor.submit(_run_single_review, cm): cm
            for cm in council_models
        }
        for future in concurrent.futures.as_completed(futures):
            cm = futures[future]
            try:
                result = future.result()
                if result is None:
                    # Model was skipped due to missing API key
                    continue
                council_results.append(result)
            except Exception as e:
                council_results.append({
                    "review": f"⚠️ Error during review: {e}",
                    "model_alias": cm["alias"],
                    "model_id": cm["id"],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "elapsed": 0.0,
                })

    # Post each council review as a separate comment
    for cr in council_results:
        # Check for agent command loop in review
        if has_agent_command(cr["review"]):
            post(
                f"⚠️ **Agent loop blocked!** Review from `{cr['model_alias']}` "
                f"contained `/agent` command(s). Blocked for safety."
            )
        else:
            post(
                f"🤖 **Council reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                f"{cr['review']}\n\n"
                f"---\n"
                f"_Council review by `/agent-workshop` Stage 2 (`{cr['model_alias']}`)_"
            )

    # Post summary comment
    n = len(council_results)
    post(
        f"## Workshop Stage 2 complete — awaiting human review\n\n"
        f"{n} model(s) have posted design critiques above. Review the feedback and "
        f"reply with your decisions on open questions. Then:\n"
        f"- Post `/agent-design` to get a revised design proposal\n"
        f"- Post `/agent-resolve` to implement directly\n"
    )

    # Aggregate totals
    total_input = design_result.get("input_tokens", 0) + sum(
        cr.get("input_tokens", 0) for cr in council_results
    )
    total_output = design_result.get("output_tokens", 0) + sum(
        cr.get("output_tokens", 0) for cr in council_results
    )
    total_cost = design_result.get("cost", 0.0) + sum(
        cr.get("cost", 0.0) for cr in council_results
    )

    return {
        "design_result": design_result,
        "council_results": council_results,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost": total_cost,
    }


# ---------------------------------------------------------------------------
# Delegate orchestration (6-stage autonomous pipeline)
# ---------------------------------------------------------------------------

DESIGN_REVISION_SYSTEM_PROMPT = (
    "You are a senior software architect. You previously produced a design proposal "
    "for a GitHub issue, and your peers on a design council have critiqued it. "
    "Your task is to revise the design based on the council's feedback.\n\n"
    "Read the original design and each council critique carefully. Then produce "
    "a revised design that:\n"
    "- Addresses valid concerns raised by reviewers\n"
    "- Explains why you rejected any concerns you disagree with\n"
    "- Incorporates useful alternative suggestions\n"
    "- Resolves open questions where possible\n\n"
    "Output a complete, revised design proposal (not just a diff from the original)."
)


SPEC_DESIGN_SYSTEM_PROMPT = (
    "You are translating an approved design into a concrete, file-by-file "
    "implementation spec for a GitHub issue. You have access to tools to read "
    "files and search the codebase.\n\n"
    "You will be given the original issue and a revised design proposal that has "
    "already been vetted by a council of reviewers. Your job is NOT to redesign — "
    "the direction is set. Your job is to turn that design into a precise "
    "implementation plan that a coding agent can execute with minimal guesswork.\n\n"
    "Use read_file and grep to examine the specific files and functions the design "
    "touches. Then call submit_analysis with a complete implementation spec in "
    "Markdown format.\n\n"
    "Your spec should include:\n"
    "1. **Files to change** — exact paths and what changes to each file\n"
    "2. **Function signatures** — new functions with their signatures, modified "
    "functions with before/after\n"
    "3. **Data structures / schemas** — any new fields, types, or config entries\n"
    "4. **Test strategy** — which existing tests need updates, which new tests to add\n"
    "5. **Edge cases and error handling** — specific scenarios to handle\n"
    "6. **Risks** — anything that could go wrong during implementation\n\n"
    "Be concrete: reference specific line numbers and existing patterns when "
    "possible. Precision matters more than prose. Do NOT re-litigate the design — "
    "implement it as given. If you find something in the codebase that makes the "
    "design impossible, flag it explicitly rather than silently changing direction."
)


COUNCIL_SPEC_REVIEW_SYSTEM_PROMPT = (
    "You are a senior software engineer participating in an implementation spec "
    "review council. You have been given an implementation spec produced from an "
    "already-approved design, and you must provide a structured critique.\n\n"
    "Focus on:\n"
    "- Concreteness — is the spec specific enough to implement without guesswork?\n"
    "- Correctness — are the proposed changes compatible with the existing codebase?\n"
    "- Missing pieces — files, functions, tests, or edge cases the spec overlooks\n"
    "- Risks during implementation — anything that will likely break\n\n"
    "Do NOT re-litigate the high-level design. That has already been reviewed and "
    "approved. Focus on implementation-level feedback only."
)


COUNCIL_SPEC_REVIEW_FORMAT = """\
Format your response EXACTLY as follows (use these exact headers):

## Spec Review by {model_alias}

**What looks good:** …

**Concreteness gaps:** …

**Missing pieces:** …

**Risks during implementation:** …
"""


def build_council_spec_review_prompt(
    *,
    issue_title,
    issue_body,
    issue_comments,
    revised_design,
    implementation_spec,
    model_alias,
):
    """Build the user prompt for a council spec review."""
    return (
        f"## Issue: {issue_title}\n\n"
        f"{issue_body}\n\n"
        f"## Discussion:\n{issue_comments}\n\n"
        f"## Approved Design (for context — do not re-review):\n\n{revised_design}\n\n"
        f"## Implementation Spec (to review):\n\n{implementation_spec}\n\n"
        f"---\n\n"
        f"Please review the implementation spec above and provide your critique. "
        f"Remember: the design is already approved, so focus on implementation-level "
        f"concerns only.\n\n"
        f"{COUNCIL_SPEC_REVIEW_FORMAT.format(model_alias=model_alias)}"
    )


SPEC_REVISION_SYSTEM_PROMPT = (
    "You are a senior software engineer. You previously produced an implementation "
    "spec from an approved design, and your peers on a spec review council have "
    "critiqued it. Your task is to revise the spec based on the council's feedback.\n\n"
    "Read the original spec and each critique carefully. Then produce a revised "
    "spec that:\n"
    "- Addresses concreteness gaps and missing pieces\n"
    "- Incorporates useful suggestions\n"
    "- Explains why you rejected any concerns you disagree with\n"
    "- Remains grounded in the approved design — do NOT re-open design questions\n\n"
    "Output a complete, revised implementation spec (not just a diff from the original)."
)

def _run_revision_call(
    *,
    model_id,
    system_prompt,
    user_content,
    extra_instructions="",
    max_tokens=8192,
):
    """Run a single non-agentic LLM call for design/code revision.

    Returns dict with keys: text, input_tokens, output_tokens, cost.
    """
    from litellm import completion as litellm_completion
    from context import completion_with_retries

    if extra_instructions:
        system_prompt += "\n\n" + extra_instructions

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    response = completion_with_retries(
        litellm_completion,
        model=model_id,
        messages=messages,
        max_tokens=max_tokens,
    )

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = getattr(response, "_hidden_params", {}).get("response_cost", None) or 0.0

    text = response.choices[0].message.content or ""

    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
    }


def run_delegate(
    *,
    model,
    model_alias,
    council_models,
    issue_title,
    issue_body,
    issue_comments="",
    extra_instructions="",
    council_extra_instructions="",
    extra_context="",
    max_iterations=15,
    max_design_iterations=None,
    wrapup_enabled=True,
    wrapup_iteration=0,
    context_keep_tool_results=0,
    post_comment_fn=None,
    design_rounds=1,
    distill_enabled=True,
    github_repo="",
    issue_number="",
):
    """Run the full delegate pipeline (6 stages, no human checkpoints).

    Stages:
        1. Design loop (agentic, same as /agent-design)
        2. Council design review (parallel, same as /agent-workshop Stage 2)
        3. Design revision — main agent reads critiques, updates design
        3a. Implementation spec loop (agentic) — conditional on design_rounds >= 2
        3b. Council spec review (parallel) — conditional on design_rounds >= 2
        3c. Spec revision (one-shot) — conditional on design_rounds >= 2
        4. Implementation / resolve (agentic, same as /agent-resolve)
        5. Council code review (parallel, same as /agent-build Stage 2)
        6. Code revision plan — main agent reads code reviews, describes fixes

    Parameters
    ----------
    model : str
        LiteLLM model ID for the main agent (design + resolve).
    model_alias : str
        Human-readable alias for the main agent.
    council_models : list of dict
        Each dict has "alias", "id", and optionally "extra_instructions".
    issue_title, issue_body, issue_comments : str
        Issue context.
    extra_instructions : str
        Additional instructions for the main agent (mode + model combined).
    council_extra_instructions : str
        Mode-level extra_instructions for council reviewers.
    extra_context : str
        Additional context for agentic loops.
    max_iterations : int
        Max iterations for code-writing agentic loops. In delegate mode
        run_delegate itself never runs a code-writing loop — the
        Stage 4 resolve step is invoked by the workflow — but callers
        pass this through for completeness / cost-model symmetry.
    max_design_iterations : int or None
        Max iterations for design/exploration agentic loops (Stage 1
        design loop and Stage 3a implementation spec loop). Falls back
        to max_iterations when None.
    wrapup_enabled : bool
        Whether graceful wrapup is enabled.
    wrapup_iteration : int
        Iteration at which to inject wrapup message.
    context_keep_tool_results : int
        Number of recent tool results to keep.
    post_comment_fn : callable or None
        Function to post a comment.
    design_rounds : int
        1 = design only (default). 2 = design + implementation spec round
        (adds Stages 3a/3b/3c between Stage 3 and Stage 4).

    Returns
    -------
    dict with keys:
        - design_result: dict from Stage 1
        - council_results: list of dicts from Stage 2
        - revised_design: str from Stage 3
        - spec_result: dict from Stage 3a (None if design_rounds < 2)
        - spec_council_results: list from Stage 3b (empty if design_rounds < 2)
        - revised_spec: str from Stage 3c (None if design_rounds < 2)
        - total_input_tokens: int
        - total_output_tokens: int
        - total_cost: float
    """
    from design_loop import run_design_loop, has_agent_command
    import concurrent.futures

    def post(body):
        if post_comment_fn:
            post_comment_fn(body)
        else:
            print(body)

    # Design/exploration budget falls back to the code-writing budget
    # when the caller doesn't differentiate. Stages 1 and 3a (both
    # agentic exploration loops) use this; Stages 4 and 6 (code-writing)
    # are driven by the workflow with max_iterations.
    if max_design_iterations is None:
        max_design_iterations = max_iterations

    all_input_tokens = 0
    all_output_tokens = 0
    all_cost = 0.0

    # =======================================================================
    # Stage 1: Design
    # =======================================================================
    post(
        f"## 🚀 Delegate Stage 1/6 — Design\n\n"
        f"Running design exploration with `{model_alias}` (`{model}`)...\n"
    )

    design_start = time.time()
    design_result = run_design_loop(
        model=model,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_comments=issue_comments,
        extra_instructions=extra_instructions,
        extra_context=extra_context,
        max_iterations=max_design_iterations,
        wrapup_enabled=wrapup_enabled,
        wrapup_iteration=wrapup_iteration,
        context_keep_tool_results=context_keep_tool_results,
        distill_enabled=distill_enabled,
    )
    design_elapsed = time.time() - design_start

    design_analysis = design_result.get("analysis", "")
    all_input_tokens += design_result.get("input_tokens", 0)
    all_output_tokens += design_result.get("output_tokens", 0)
    all_cost += design_result.get("cost", 0.0)

    if not design_analysis:
        post(
            "⚠️ **Delegate Stage 1 did not produce a design.** "
            "The design agent may have exhausted all iterations without "
            "calling `submit_analysis`. Aborting delegate pipeline."
        )
        return {
            "design_result": design_result,
            "council_results": [],
            "revised_design": None,
            "spec_result": None,
            "spec_council_results": [],
            "revised_spec": None,
            "total_input_tokens": all_input_tokens,
            "total_output_tokens": all_output_tokens,
            "total_cost": all_cost,
        }

    if has_agent_command(design_analysis):
        post(
            "⚠️ **Agent loop blocked!** The design analysis contained "
            "`/agent` command(s). Aborting delegate pipeline for safety."
        )
        return {
            "design_result": design_result,
            "council_results": [],
            "revised_design": None,
            "spec_result": None,
            "spec_council_results": [],
            "revised_spec": None,
            "total_input_tokens": all_input_tokens,
            "total_output_tokens": all_output_tokens,
            "total_cost": all_cost,
        }

    design_cost_block = _build_stage_cost_block(
        github_repo=github_repo,
        issue_number=issue_number,
        input_tokens=design_result.get("input_tokens", 0),
        output_tokens=design_result.get("output_tokens", 0),
        cost=design_result.get("cost", 0.0),
        elapsed=design_elapsed,
        output_text=design_analysis,
    )
    post(
        f"🤖 **Model:** `{model_alias}` (`{model}`)\n\n"
        f"{design_analysis}\n\n"
        f"---\n"
        f"_Design analysis by `/agent-delegate` Stage 1 (`{model_alias}`)_\n\n"
        f"{design_cost_block}"
    )

    # =======================================================================
    # Stage 2: Council Design Review
    # =======================================================================
    council_results = []
    if council_models:
        post(
            f"## 🏛️ Delegate Stage 2/6 — Council Design Review\n\n"
            f"Requesting critiques from {len(council_models)} council member(s): "
            f"{', '.join('`' + m['alias'] + '`' for m in council_models)}...\n"
        )

        def _run_single_review(council_model):
            model_id = council_model["id"]
            key_name = _get_required_api_key_name(model_id)
            if key_name is not None:
                key_value = os.environ.get(key_name, "")
                if not key_value:
                    print(
                        f"Skipping {council_model['alias']} — API key not configured "
                        f"({key_name} is empty or missing)",
                        flush=True,
                    )
                    return None

            model_extra = council_model.get("extra_instructions", "")
            reviewer_extra = "\n\n".join(p for p in [council_extra_instructions, model_extra] if p)

            review_start = time.time()
            result = run_council_review(
                model_id=model_id,
                model_alias=council_model["alias"],
                issue_title=issue_title,
                issue_body=issue_body,
                issue_comments=issue_comments,
                design_analysis=design_analysis,
                extra_instructions=reviewer_extra,
            )
            result["elapsed"] = time.time() - review_start
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(council_models)) as executor:
            futures = {
                executor.submit(_run_single_review, cm): cm
                for cm in council_models
            }
            for future in concurrent.futures.as_completed(futures):
                cm = futures[future]
                try:
                    result = future.result()
                    if result is None:
                        continue
                    council_results.append(result)
                except Exception as e:
                    council_results.append({
                        "review": f"⚠️ Error during review: {e}",
                        "model_alias": cm["alias"],
                        "model_id": cm["id"],
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost": 0.0,
                        "elapsed": 0.0,
                    })

        for cr in council_results:
            if has_agent_command(cr["review"]):
                post(
                    f"⚠️ **Agent loop blocked!** Review from `{cr['model_alias']}` "
                    f"contained `/agent` command(s). Blocked for safety."
                )
            else:
                post(
                    f"🤖 **Council reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                    f"{cr['review']}\n\n"
                    f"---\n"
                    f"_Council review by `/agent-delegate` Stage 2 (`{cr['model_alias']}`)_"
                )

            all_input_tokens += cr.get("input_tokens", 0)
            all_output_tokens += cr.get("output_tokens", 0)
            all_cost += cr.get("cost", 0.0)
    else:
        post(
            "## 🏛️ Delegate Stage 2/6 — Council Design Review\n\n"
            "⚠️ No council models configured. Skipping council design review.\n"
        )

    # =======================================================================
    # Stage 3: Design Revision
    # =======================================================================
    post(
        f"## 🔄 Delegate Stage 3/6 — Design Revision\n\n"
        f"Main agent (`{model_alias}`) is revising the design based on council feedback...\n"
    )

    critiques_text = "\n\n---\n\n".join(
        f"### Critique by {cr['model_alias']}\n\n{cr['review']}"
        for cr in council_results
        if not has_agent_command(cr.get("review", ""))
    )

    revision_user_content = (
        f"## Original Design Proposal\n\n{design_analysis}\n\n"
        f"## Council Critiques\n\n{critiques_text}\n\n"
        f"---\n\n"
        f"Please produce a revised, complete design proposal that addresses "
        f"the council's feedback."
    )

    revision_start = time.time()
    revision_result = _run_revision_call(
        model_id=model,
        system_prompt=DESIGN_REVISION_SYSTEM_PROMPT,
        user_content=revision_user_content,
        extra_instructions=extra_instructions,
        max_tokens=8192,
    )
    revision_elapsed = time.time() - revision_start

    revised_design = revision_result["text"]
    all_input_tokens += revision_result["input_tokens"]
    all_output_tokens += revision_result["output_tokens"]
    all_cost += revision_result["cost"]

    if has_agent_command(revised_design):
        post(
            "⚠️ **Agent loop blocked!** The revised design contained "
            "`/agent` command(s). Blocked for safety."
        )
    else:
        revision_cost_block = _build_stage_cost_block(
            github_repo=github_repo,
            issue_number=issue_number,
            input_tokens=revision_result["input_tokens"],
            output_tokens=revision_result["output_tokens"],
            cost=revision_result["cost"],
            elapsed=revision_elapsed,
            output_text=revised_design,
        )
        post(
            f"🤖 **Model:** `{model_alias}` (`{model}`)\n\n"
            f"{revised_design}\n\n"
            f"---\n"
            f"_Revised design by `/agent-delegate` Stage 3 (`{model_alias}`)_\n\n"
            f"{revision_cost_block}"
        )

    # =======================================================================
    # Stages 3a-3c: Implementation Spec Round (conditional)
    # =======================================================================
    spec_result = None
    spec_council_results = []
    revised_spec = None
    spec_revision_result = None

    if design_rounds >= 2:
        # ---- Stage 3a: Implementation spec (agentic) ----
        post(
            f"## 📐 Delegate Stage 3a — Implementation Spec\n\n"
            f"Main agent (`{model_alias}`) is translating the revised design into "
            f"a concrete implementation spec...\n"
        )

        # Pass the revised design as extra context to the spec loop.  It's
        # cleaner to inject it directly as extra_context than to pull it out
        # of the issue comment thread during the loop.
        spec_extra_context = extra_context
        if spec_extra_context:
            spec_extra_context += "\n\n"
        spec_extra_context += (
            f"## Approved Design (from Stage 3 — implement this, do not redesign)\n\n"
            f"{revised_design}"
        )

        spec_start = time.time()
        spec_result = run_design_loop(
            model=model,
            issue_title=issue_title,
            issue_body=issue_body,
            issue_comments=issue_comments,
            extra_instructions=extra_instructions,
            extra_context=spec_extra_context,
            max_iterations=max_design_iterations,
            wrapup_enabled=wrapup_enabled,
            wrapup_iteration=wrapup_iteration,
            context_keep_tool_results=context_keep_tool_results,
            distill_enabled=distill_enabled,
            system_prompt=SPEC_DESIGN_SYSTEM_PROMPT,
        )
        spec_elapsed = time.time() - spec_start

        implementation_spec = spec_result.get("analysis", "")
        all_input_tokens += spec_result.get("input_tokens", 0)
        all_output_tokens += spec_result.get("output_tokens", 0)
        all_cost += spec_result.get("cost", 0.0)

        if not implementation_spec:
            post(
                "⚠️ **Delegate Stage 3a did not produce an implementation spec.** "
                "The spec agent may have exhausted all iterations without "
                "calling `submit_analysis`. Aborting delegate pipeline."
            )
            return {
                "design_result": design_result,
                "design_analysis": design_analysis,
                "council_results": council_results,
                "revised_design": revised_design,
                "revision_result": revision_result,
                "spec_result": spec_result,
                "spec_council_results": [],
                "revised_spec": None,
                "spec_revision_result": None,
                "total_input_tokens": all_input_tokens,
                "total_output_tokens": all_output_tokens,
                "total_cost": all_cost,
            }

        if has_agent_command(implementation_spec):
            post(
                "⚠️ **Agent loop blocked!** The implementation spec contained "
                "`/agent` command(s). Aborting delegate pipeline for safety."
            )
            return {
                "design_result": design_result,
                "design_analysis": design_analysis,
                "council_results": council_results,
                "revised_design": revised_design,
                "revision_result": revision_result,
                "spec_result": spec_result,
                "spec_council_results": [],
                "revised_spec": None,
                "spec_revision_result": None,
                "total_input_tokens": all_input_tokens,
                "total_output_tokens": all_output_tokens,
                "total_cost": all_cost,
            }

        spec_cost_block = _build_stage_cost_block(
            github_repo=github_repo,
            issue_number=issue_number,
            input_tokens=spec_result.get("input_tokens", 0),
            output_tokens=spec_result.get("output_tokens", 0),
            cost=spec_result.get("cost", 0.0),
            elapsed=spec_elapsed,
            output_text=implementation_spec,
        )
        post(
            f"🤖 **Model:** `{model_alias}` (`{model}`)\n\n"
            f"{implementation_spec}\n\n"
            f"---\n"
            f"_Implementation spec by `/agent-delegate` Stage 3a (`{model_alias}`)_\n\n"
            f"{spec_cost_block}"
        )

        # ---- Stage 3b: Council spec review ----
        if council_models:
            post(
                f"## 🏛️ Delegate Stage 3b — Council Spec Review\n\n"
                f"Requesting implementation-level critiques from "
                f"{len(council_models)} council member(s): "
                f"{', '.join('`' + m['alias'] + '`' for m in council_models)}...\n"
            )

            def _run_single_spec_review(council_model):
                model_id = council_model["id"]
                key_name = _get_required_api_key_name(model_id)
                if key_name is not None:
                    key_value = os.environ.get(key_name, "")
                    if not key_value:
                        print(
                            f"Skipping {council_model['alias']} — API key not configured "
                            f"({key_name} is empty or missing)",
                            flush=True,
                        )
                        return None

                model_extra = council_model.get("extra_instructions", "")
                reviewer_extra = "\n\n".join(
                    p for p in [council_extra_instructions, model_extra] if p
                )

                user_content = build_council_spec_review_prompt(
                    issue_title=issue_title,
                    issue_body=issue_body,
                    issue_comments=issue_comments,
                    revised_design=revised_design,
                    implementation_spec=implementation_spec,
                    model_alias=council_model["alias"],
                )

                review_start = time.time()
                result = run_council_review(
                    model_id=model_id,
                    model_alias=council_model["alias"],
                    issue_title=issue_title,
                    issue_body=issue_body,
                    issue_comments=issue_comments,
                    design_analysis=implementation_spec,  # unused when override is set
                    extra_instructions=reviewer_extra,
                    system_prompt_override=COUNCIL_SPEC_REVIEW_SYSTEM_PROMPT,
                    user_content_override=user_content,
                )
                result["elapsed"] = time.time() - review_start
                return result

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(council_models)) as executor:
                futures = {
                    executor.submit(_run_single_spec_review, cm): cm
                    for cm in council_models
                }
                for future in concurrent.futures.as_completed(futures):
                    cm = futures[future]
                    try:
                        result = future.result()
                        if result is None:
                            continue
                        spec_council_results.append(result)
                    except Exception as e:
                        spec_council_results.append({
                            "review": f"⚠️ Error during review: {e}",
                            "model_alias": cm["alias"],
                            "model_id": cm["id"],
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cost": 0.0,
                            "elapsed": 0.0,
                        })

            for cr in spec_council_results:
                if has_agent_command(cr["review"]):
                    post(
                        f"⚠️ **Agent loop blocked!** Spec review from "
                        f"`{cr['model_alias']}` contained `/agent` command(s). "
                        f"Blocked for safety."
                    )
                else:
                    post(
                        f"🤖 **Council spec reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                        f"{cr['review']}\n\n"
                        f"---\n"
                        f"_Council spec review by `/agent-delegate` Stage 3b (`{cr['model_alias']}`)_"
                    )

                all_input_tokens += cr.get("input_tokens", 0)
                all_output_tokens += cr.get("output_tokens", 0)
                all_cost += cr.get("cost", 0.0)
        else:
            post(
                "## 🏛️ Delegate Stage 3b — Council Spec Review\n\n"
                "⚠️ No council models configured. Skipping council spec review.\n"
            )

        # ---- Stage 3c: Spec revision (one-shot) ----
        post(
            f"## 🔄 Delegate Stage 3c — Spec Revision\n\n"
            f"Main agent (`{model_alias}`) is revising the implementation spec "
            f"based on council feedback...\n"
        )

        spec_critiques_text = "\n\n---\n\n".join(
            f"### Critique by {cr['model_alias']}\n\n{cr['review']}"
            for cr in spec_council_results
            if not has_agent_command(cr.get("review", ""))
        )

        spec_revision_user_content = (
            f"## Approved Design (for context — do not re-open)\n\n{revised_design}\n\n"
            f"## Original Implementation Spec\n\n{implementation_spec}\n\n"
            f"## Council Critiques\n\n{spec_critiques_text}\n\n"
            f"---\n\n"
            f"Please produce a revised, complete implementation spec that addresses "
            f"the council's feedback."
        )

        spec_revision_start = time.time()
        spec_revision_result = _run_revision_call(
            model_id=model,
            system_prompt=SPEC_REVISION_SYSTEM_PROMPT,
            user_content=spec_revision_user_content,
            extra_instructions=extra_instructions,
            max_tokens=8192,
        )
        spec_revision_elapsed = time.time() - spec_revision_start

        revised_spec = spec_revision_result["text"]
        all_input_tokens += spec_revision_result["input_tokens"]
        all_output_tokens += spec_revision_result["output_tokens"]
        all_cost += spec_revision_result["cost"]

        if has_agent_command(revised_spec):
            post(
                "⚠️ **Agent loop blocked!** The revised spec contained "
                "`/agent` command(s). Blocked for safety."
            )
            revised_spec = None
        else:
            spec_revision_cost_block = _build_stage_cost_block(
                github_repo=github_repo,
                issue_number=issue_number,
                input_tokens=spec_revision_result["input_tokens"],
                output_tokens=spec_revision_result["output_tokens"],
                cost=spec_revision_result["cost"],
                elapsed=spec_revision_elapsed,
                output_text=revised_spec,
            )
            post(
                f"🤖 **Model:** `{model_alias}` (`{model}`)\n\n"
                f"{revised_spec}\n\n"
                f"---\n"
                f"_Revised implementation spec by `/agent-delegate` Stage 3c (`{model_alias}`)_\n\n"
                f"{spec_revision_cost_block}"
            )

    # =======================================================================
    # Stages 4-6: Implementation + Code Review + Revision
    # =======================================================================
    # Stages 4-6 (resolve, code review council, code revision) require the
    # resolve agent infrastructure (branch setup, tool execution, PR creation)
    # which runs as a separate workflow job.  The revised design from Stage 3
    # (and revised spec from Stage 3c if design_rounds >= 2) is passed to the
    # resolve job via EXTRA_FILES.
    #
    # The workflow job for delegate mode will:
    #   - Run Stages 1-3 (and optionally 3a-3c) here
    #   - Pass the revised design (and revised spec) to the resolve step
    #   - After resolve creates a PR, run Stage 5 (council code review)
    #   - Post Stage 6 (code revision plan) as a comment

    stages_done_label = "Stages 1-3c" if design_rounds >= 2 else "Stages 1-3"
    post(
        f"## Delegate {stages_done_label} complete\n\n"
        f"Proceeding to implementation (Stage 4)...\n"
    )

    # No separate aggregate-cost block here — each per-stage cost block above
    # carries a canonical cumulative table (via compute_cumulative_table), so
    # the cumulative on the last reported stage IS the running total. The old
    # bespoke "Delegate Stages 1-3c Aggregate Cost" block used the per-step
    # cost format (with bold **$X.XX**), which the cumulative-cost scanner
    # would have picked up as a prior per-step cost — risking quadratic
    # double-counting on any subsequent /agent-* invocation on the issue.

    return {
        "design_result": design_result,
        "design_analysis": design_analysis,
        "council_results": council_results,
        "revised_design": revised_design,
        "revision_result": revision_result,
        "spec_result": spec_result,
        "spec_council_results": spec_council_results,
        "revised_spec": revised_spec,
        "spec_revision_result": spec_revision_result,
        "total_input_tokens": all_input_tokens,
        "total_output_tokens": all_output_tokens,
        "total_cost": all_cost,
    }
