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

import gzip
import json
import math
import os
import re
import sys
import time

# Ensure sibling modules are importable when run from the workflow
sys.path.insert(0, os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# Cost formatting helpers
# ---------------------------------------------------------------------------

def _fmt_tok(n):
    n = int(n)
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{round(v)}M" if v >= 10 else f"{round(v, 1)}M"
    elif n >= 1_000:
        v = n / 1_000
        return f"{round(v)}K" if v >= 10 else f"{round(v, 1)}K"
    return str(n)


def _fmt_ela(s):
    s = int(s)
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def _fmt_bpd(text, cost):
    if cost <= 0:
        return 'N/A'
    data = text.encode('utf-8') if isinstance(text, str) else text
    bpd = len(gzip.compress(data)) / cost  # compressed bytes / dollar
    if bpd >= 1_000_000:
        return f"{bpd / 1_000_000:.1f} Mbit/$"
    return f"{bpd / 1_000:.1f} Kbit/$"


def _build_cost_table(input_tokens, output_tokens, cost, elapsed, output_text):
    rounded = math.ceil(cost * 100) / 100
    rows = [
        ('Time', _fmt_ela(elapsed)),
        ('Input', _fmt_tok(input_tokens) + ' tokens'),
        ('Output', _fmt_tok(output_tokens) + ' tokens'),
        ('Bits/$', _fmt_bpd(output_text, cost)),
        ('**Cost**', f'**${rounded:.2f}**'),
    ]
    lines = ['---', '', '### 💰 Cost', '', '| Metric | Value |', '|--------|-------|']
    lines += [f'| {k} | {v} |' for k, v in rows]
    return '\n'.join(lines)


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
        The Stage 1 design analysis to review.
    extra_instructions : str
        Additional instructions appended to the council reviewer system prompt.
        Should be the combination of mode-level and model-level extra_instructions.
    api_keys : dict or None
        Optional mapping of env var names to values to set before the call.

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

    user_content = build_council_review_prompt(
        issue_title=issue_title,
        issue_body=issue_body,
        issue_comments=issue_comments,
        design_analysis=design_analysis,
        model_alias=model_alias,
    )

    system_prompt = COUNCIL_REVIEW_SYSTEM_PROMPT
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
):
    """Run Stage 2 council code reviews for build mode.

    Runs each council model's review in parallel (non-agentic). Posts each
    review via post_comment_fn (defaults to print if None).

    extra_instructions is the mode-level extra_instructions string; each council
    member's model-level extra_instructions (from council_model["extra_instructions"])
    is appended per-reviewer.

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
            "## 🏛️ Build Stage 2 — Council Code Review\n\n"
            "⚠️ No council models configured. Skipping council code review.\n"
        )
        return {
            "council_results": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
        }

    post(
        f"## 🏛️ Build Stage 2 — Council Code Review\n\n"
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
            cost_table = _build_cost_table(
                input_tokens=cr.get("input_tokens", 0),
                output_tokens=cr.get("output_tokens", 0),
                cost=cr.get("cost", 0.0),
                elapsed=cr.get("elapsed", 0.0),
                output_text=cr.get("review", ""),
            )
            post(
                f"🤖 **Council reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                f"{cr['review']}\n\n"
                f"---\n"
                f"_Council code review by `/agent-build` Stage 2 (`{cr['model_alias']}`)_\n\n"
                f"{cost_table}"
            )

    n = len(council_results)
    post(
        f"## Build Stage 2 complete — awaiting human review\n\n"
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
            cost_table = _build_cost_table(
                input_tokens=cr.get("input_tokens", 0),
                output_tokens=cr.get("output_tokens", 0),
                cost=cr.get("cost", 0.0),
                elapsed=cr.get("elapsed", 0.0),
                output_text=cr.get("review", ""),
            )
            post(
                f"🤖 **Council reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                f"{cr['review']}\n\n"
                f"---\n"
                f"_Council review by `/agent-workshop` Stage 2 (`{cr['model_alias']}`)_\n\n"
                f"{cost_table}"
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

CODE_REVISION_SYSTEM_PROMPT = (
    "You are a senior software engineer. You previously implemented a solution "
    "for a GitHub issue, and your peers on a code review council have reviewed "
    "the resulting pull request. Your task is to describe what changes should be "
    "made to address the code review feedback.\n\n"
    "Read the original PR diff and each code review carefully. Then produce "
    "a revision plan that:\n"
    "- Addresses valid concerns raised by reviewers\n"
    "- Explains why you rejected any concerns you disagree with\n"
    "- Incorporates useful suggestions\n"
    "- Lists specific files and changes to make\n\n"
    "Be concrete and actionable — the implementation agent will use your plan."
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
    wrapup_enabled=True,
    wrapup_iteration=0,
    context_keep_tool_results=0,
    post_comment_fn=None,
):
    """Run the full delegate pipeline (6 stages, no human checkpoints).

    Stages:
        1. Design loop (agentic, same as /agent-design)
        2. Council design review (parallel, same as /agent-workshop Stage 2)
        3. Design revision — main agent reads critiques, updates design
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
        Max iterations for agentic loops (design + resolve).
    wrapup_enabled : bool
        Whether graceful wrapup is enabled.
    wrapup_iteration : int
        Iteration at which to inject wrapup message.
    context_keep_tool_results : int
        Number of recent tool results to keep.
    post_comment_fn : callable or None
        Function to post a comment.

    Returns
    -------
    dict with keys:
        - design_result: dict from Stage 1
        - council_results: list of dicts from Stage 2
        - revised_design: dict from Stage 3
        - resolve_result: dict from Stage 4 (placeholder — resolve runs externally)
        - code_review_results: list of dicts from Stage 5 (placeholder)
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
        max_iterations=max_iterations,
        wrapup_enabled=wrapup_enabled,
        wrapup_iteration=wrapup_iteration,
        context_keep_tool_results=context_keep_tool_results,
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
            "total_input_tokens": all_input_tokens,
            "total_output_tokens": all_output_tokens,
            "total_cost": all_cost,
        }

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
        f"_Design analysis by `/agent-delegate` Stage 1 (`{model_alias}`)_\n\n"
        f"{design_cost_table}"
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
                cost_table = _build_cost_table(
                    input_tokens=cr.get("input_tokens", 0),
                    output_tokens=cr.get("output_tokens", 0),
                    cost=cr.get("cost", 0.0),
                    elapsed=cr.get("elapsed", 0.0),
                    output_text=cr.get("review", ""),
                )
                post(
                    f"🤖 **Council reviewer:** `{cr['model_alias']}` (`{cr['model_id']}`)\n\n"
                    f"{cr['review']}\n\n"
                    f"---\n"
                    f"_Council review by `/agent-delegate` Stage 2 (`{cr['model_alias']}`)_\n\n"
                    f"{cost_table}"
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
        revision_cost_table = _build_cost_table(
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
            f"{revision_cost_table}"
        )

    # =======================================================================
    # Stages 4-6: Implementation + Code Review + Revision
    # =======================================================================
    # Stages 4-6 (resolve, code review council, code revision) require the
    # resolve agent infrastructure (branch setup, tool execution, PR creation)
    # which runs as a separate workflow job.  The revised design from Stage 3
    # is passed to the resolve job via the stage3_revised_design output.
    #
    # The workflow job for delegate mode will:
    #   - Run Stages 1-3 here (design + council + revision)
    #   - Pass the revised design to the resolve step as extra context
    #   - After resolve creates a PR, run Stage 5 (council code review)
    #   - Post Stage 6 (code revision plan) as a comment

    post(
        f"## Delegate Stages 1-3 complete\n\n"
        f"Design exploration, council review, and design revision are done.\n"
        f"Proceeding to implementation (Stage 4)...\n"
    )

    # Build aggregate cost table for Stages 1-3
    stages_1_3_cost_table = _build_cost_table(
        input_tokens=all_input_tokens,
        output_tokens=all_output_tokens,
        cost=all_cost,
        elapsed=time.time() - design_start,
        output_text=revised_design,
    )
    post(
        f"### 📊 Delegate Stages 1-3 Aggregate Cost\n\n"
        f"{stages_1_3_cost_table}"
    )

    return {
        "design_result": design_result,
        "design_analysis": design_analysis,
        "council_results": council_results,
        "revised_design": revised_design,
        "revision_result": revision_result,
        "total_input_tokens": all_input_tokens,
        "total_output_tokens": all_output_tokens,
        "total_cost": all_cost,
    }
