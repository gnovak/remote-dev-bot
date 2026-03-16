"""Workshop mode: multi-model design council with human checkpoints.

MVP scope: Stages 1 (design) and 2 (council review).

Stage 1 — Design: Run the agentic design loop (same as /agent-design) using
the configured default model.

Stage 2 — Council review: Each council model posts a structured peer critique
of the Stage 1 design. Council reviews run simultaneously (not sequentially)
so critiques are maximally independent.

After Stage 2, the bot posts a summary comment and stops.  Human reviews the
critiques, then optionally triggers Stage 3 (adjust) — implemented in a
follow-up.
"""

import json
import os
import re
import sys

# Ensure sibling modules are importable when run from the workflow
sys.path.insert(0, os.path.dirname(__file__))


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

    messages = [
        {"role": "system", "content": COUNCIL_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    response = litellm_completion(
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
# Council filtering
# ---------------------------------------------------------------------------

def resolve_council_models(models, design_alias, council_config=None):
    """Resolve the list of council models.

    Parameters
    ----------
    models : dict
        All configured models (alias -> {"id": ...}).
    design_alias : str
        The alias of the design model (excluded by default).
    council_config : list or None
        Explicit council list from mode config. If empty/None, defaults to
        all models except the design model.

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
        # Default: all models except the design model (no self-review)
        for alias, cfg in models.items():
            if alias != design_alias:
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
        Each dict has "alias" and "id" keys.
    issue_title, issue_body, issue_comments : str
        Issue context.
    extra_instructions, extra_context : str
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

    # Post design analysis
    post(
        f"🤖 **Model:** `{model_alias}` (`{model}`)\n\n"
        f"{design_analysis}\n\n"
        f"---\n"
        f"_Design analysis by `/agent-workshop` Stage 1 (`{model_alias}`)_"
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
        return run_council_review(
            model_id=council_model["id"],
            model_alias=council_model["alias"],
            issue_title=issue_title,
            issue_body=issue_body,
            issue_comments=issue_comments,
            design_analysis=design_analysis,
        )

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
                council_results.append(result)
            except Exception as e:
                council_results.append({
                    "review": f"⚠️ Error during review: {e}",
                    "model_alias": cm["alias"],
                    "model_id": cm["id"],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
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
        f"{n} model(s) have posted design critiques above. Please review, reply with "
        f"decisions on open questions, and then post `/agent-workshop-adjust` to "
        f"continue to Stage 3.\n"
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
