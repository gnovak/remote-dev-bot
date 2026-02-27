#!/usr/bin/env bash
# E2E tests for remote-dev-bot.
#
# Creates test issues in remote-dev-bot-test, triggers the agent,
# waits for workflow completion, and verifies results.
#
# Usage:
#   ./tests/e2e.sh [--branch <branch>] [--test <name>] [--provider <name>]
#                  [--all-models] [--compiled]
#
#   --branch      Branch to test (default: main). Sets e2e-test pointer to this branch.
#   --test        Run a specific test only (default: all)
#   --provider    Run only tests for a specific model family (claude/gpt/gemini)
#   --all-models  Test every model alias, not just one per provider
#   --compiled    Test compiled workflows instead of shim (pre-release validation)

set -euo pipefail

TEST_REPO="gnovak/remote-dev-bot-test"
POLL_INTERVAL=60
TIMEOUT=1800  # 30 minutes

# --- Argument parsing ---

BRANCH="main"
FILTER_TEST=""
FILTER_PROVIDER=""
ALL_MODELS=false
USE_COMPILED=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --branch) BRANCH="$2"; shift 2 ;;
        --test) FILTER_TEST="$2"; shift 2 ;;
        --provider) FILTER_PROVIDER="$2"; shift 2 ;;
        --all-models) ALL_MODELS=true; shift ;;
        --compiled) USE_COMPILED=true; shift ;;
        -h|--help)
            head -17 "$0" | tail -13
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- GraphQL quota guard ---
# Fail fast if the bot account's hourly quota is too low to complete a run.
# A single all-models e2e run costs ~450-500 GraphQL points (polling + API calls).

check_graphql_quota() {
    local min_points=500
    local result remaining reset_ts reset_time
    result=$(gh api rate_limit --jq '.resources.graphql | "\(.remaining) \(.reset)"' 2>/dev/null || true)
    if [[ -z "$result" ]]; then
        echo "==> Warning: could not check GraphQL rate limit — proceeding anyway"
        return
    fi
    remaining=$(echo "$result" | cut -d' ' -f1)
    reset_ts=$(echo "$result" | cut -d' ' -f2)
    reset_time=$(python3 -c "
import datetime
ts = ${reset_ts}
local_t = datetime.datetime.fromtimestamp(ts)
utc_t = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None)
mins = max(0, int((local_t - datetime.datetime.now()).total_seconds() / 60))
print(f'{local_t.strftime(\"%H:%M:%S\")} local / {utc_t.strftime(\"%H:%M:%S\")} UTC (in {mins} min)')
" 2>/dev/null || echo "unknown")
    if [[ "$remaining" -lt "$min_points" ]]; then
        echo "ERROR: GraphQL quota too low: ${remaining} points remaining (need ${min_points}+)." >&2
        echo "ERROR: Quota resets at ${reset_time}. Please retry after that." >&2
        exit 1
    fi
    echo "==> GraphQL quota: ${remaining} points remaining (resets ${reset_time})."
}

check_graphql_quota

# --- Test case definitions ---
# Parallel arrays — index i corresponds to the same test across all arrays.
# test_type: "resolve" expects a PR, "design" expects a comment

all_names=()
all_titles=()
all_bodies=()
all_cmds=()
all_providers=()
all_types=()

add_test() {
    all_names+=("$1"); all_titles+=("$2"); all_bodies+=("$3")
    all_cmds+=("$4"); all_providers+=("$5"); all_types+=("${6:-resolve}")
}

if $ALL_MODELS; then
    # Generate a test for every model alias in the config file.
    config_file="remote-dev-bot.yaml"
    if [[ ! -f "$config_file" ]]; then
        echo "ERROR: $config_file not found. Run from repo root." >&2
        exit 1
    fi

    # Read all model aliases and their model family names from the config.
    # Tasks modify README.md rather than creating new files — Gemini models use
    # insert_line=0 when creating files from scratch, which sets wrong file
    # ownership and causes git add to fail with Permission denied. See #272.
    while IFS='|' read -r alias model_family; do
        safe_alias="${alias//-/_}"
        add_test "$alias" "Test ($alias): update README for ${alias}" \
            "Add a '## ${alias}' section to README.md containing a Python code block with a function hello_${safe_alias}() that returns 'Hello from ${alias}!'." \
            "/agent-resolve-$alias" "$model_family" "resolve"
    done < <(python3 -c "
import yaml, sys
with open('$config_file') as f:
    config = yaml.safe_load(f)
# Map provider prefixes to model family names
provider_to_family = {'anthropic': 'claude', 'openai': 'gpt', 'gemini': 'gemini'}
for alias, info in config.get('models', {}).items():
    model_id = info.get('id', '')
    provider = model_id.split('/')[0] if '/' in model_id else 'unknown'
    model_family = provider_to_family.get(provider, provider)
    print(f'{alias}|{model_family}')
")

    # Default model test (resolve mode, no alias)
    add_test "default-model" "Test (default): update README for default" \
        "Add a '## Default' section to README.md containing a Python code block with a function hello_default() that returns 'Hello from default!'." \
        "/agent-resolve" "all" "resolve"
else
    # Smoke tests: one small model per provider + default
    add_test "default-model" "Test: add hello.py" \
        "Create a file hello.py with a function hello() that returns 'Hello, world!'" \
        "/agent-resolve" "all" "resolve"

    add_test "claude" "Test: add greet.py" \
        "Create a file greet.py with a function greet(name) that returns f'Hello, {name}!'" \
        "/agent-resolve-claude-small" "claude" "resolve"

    add_test "gpt" "Test: add wave.py" \
        "Create a file wave.py with a function wave() that returns 'Wave!'" \
        "/agent-resolve-gpt-small" "gpt" "resolve"

    # Modify README.md rather than creating a new file — Gemini models use
    # insert_line=0 when creating files from scratch, which sets wrong file
    # ownership and causes git add to fail with Permission denied. See #272.
    add_test "gemini" "Test: update README with hi function" \
        "Add a '## Gemini' section to README.md containing a Python code block with a function hi() that returns 'Hi!'." \
        "/agent-resolve-gemini-small" "gemini" "resolve"

    # Design mode smoke test
    add_test "design" "Test: design analysis" \
        "Discuss whether this test repo should have a README. What would you include?" \
        "/agent-design" "all" "design"

    # Explore mode smoke test (dev-only feature)
    add_test "explore" "Test: explore analysis" \
        "Discuss the design trade-offs of storing configuration in YAML vs TOML vs JSON for a developer tooling project." \
        "/agent-explore" "all" "explore"

    # Inline args smoke test: pass max_iterations as inline arg
    add_test "inline-args" "Test: inline max_iterations" \
        "Create a file inline_test.py with a stub function stub() that returns None." \
        $'/agent-resolve\nmax_iterations = 10' \
        "all" "resolve"
fi

# --- Helpers ---

log() { echo "==> $*"; }
err() { echo "ERROR: $*" >&2; }

# Extract cost from a Cost Summary comment body.
# Returns the cost as a decimal string (e.g., "1.23") or "0.00" if not found.
parse_cost_from_comment() {
    local body="$1"
    local result
    # Look for "| **Estimated cost** | **$X.XX** |" pattern
    result=$(echo "$body" | grep -oE '\*\*\$[0-9]+\.[0-9]+\*\*' | head -1 | tr -d '*$')
    if [[ -n "$result" ]]; then
        echo "$result"
    else
        echo "0.00"
    fi
}

cleanup_issues=()
cleanup_branches=()

# --- Compiled workflow swap ---
# When --compiled is used, we replace the shim (agent.yml) in the test repo
# with agent-resolve.yml, add agent-design.yml, run the full test suite, then
# restore the original shim and remove agent-design.yml.

ORIGINAL_SHIM_CONTENT=""  # base64-encoded original shim
ORIGINAL_SHIM_SHA=""      # SHA for restoring
DESIGN_WORKFLOW_SHA=""     # SHA for removing agent-design.yml on cleanup
REVIEW_WORKFLOW_SHA=""     # SHA for removing agent-review.yml on cleanup

install_compiled_workflow() {
    log "Compiling workflows..."
    python3 scripts/compile.py /tmp/compiled-workflows

    log "Saving original shim from $TEST_REPO..."
    local shim_response
    shim_response=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent.yml")
    ORIGINAL_SHIM_CONTENT=$(echo "$shim_response" | jq -r '.content' | tr -d '\n')
    ORIGINAL_SHIM_SHA=$(echo "$shim_response" | jq -r '.sha')

    log "Replacing shim with compiled resolve workflow..."
    local resolve_content
    resolve_content=$(base64 < /tmp/compiled-workflows/agent-resolve.yml | tr -d '\n')

    gh api "repos/$TEST_REPO/contents/.github/workflows/agent.yml" \
        --method PUT \
        -f message="E2E: swap shim for compiled resolve workflow (pre-release test)" \
        -f content="$resolve_content" \
        -f sha="$ORIGINAL_SHIM_SHA" >/dev/null

    log "Adding compiled design workflow..."
    local design_content
    design_content=$(base64 < /tmp/compiled-workflows/agent-design.yml | tr -d '\n')

    local design_response
    design_response=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-design.yml" \
        --method PUT \
        -f message="E2E: add compiled design workflow (pre-release test)" \
        -f content="$design_content" 2>&1) || {
        # File may already exist; get its SHA and update
        local existing_sha
        existing_sha=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-design.yml" \
            --jq '.sha' 2>/dev/null || echo "")
        if [[ -n "$existing_sha" ]]; then
            design_response=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-design.yml" \
                --method PUT \
                -f message="E2E: update compiled design workflow (pre-release test)" \
                -f content="$design_content" \
                -f sha="$existing_sha")
        fi
    }
    DESIGN_WORKFLOW_SHA=$(echo "$design_response" | jq -r '.content.sha' 2>/dev/null || echo "")

    log "Adding compiled review workflow..."
    local review_content
    review_content=$(base64 < /tmp/compiled-workflows/agent-review.yml | tr -d '\n')

    local review_response
    review_response=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-review.yml" \
        --method PUT \
        -f message="E2E: add compiled review workflow (pre-release test)" \
        -f content="$review_content" 2>&1) || {
        # File may already exist; get its SHA and update
        local existing_sha
        existing_sha=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-review.yml" \
            --jq '.sha' 2>/dev/null || echo "")
        if [[ -n "$existing_sha" ]]; then
            review_response=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-review.yml" \
                --method PUT \
                -f message="E2E: update compiled review workflow (pre-release test)" \
                -f content="$review_content" \
                -f sha="$existing_sha")
        fi
    }
    REVIEW_WORKFLOW_SHA=$(echo "$review_response" | jq -r '.content.sha' 2>/dev/null || echo "")

    log "Compiled workflows installed. Waiting 10s for GitHub to register..."
    sleep 10
}

restore_shim() {
    if [[ -z "$ORIGINAL_SHIM_CONTENT" ]]; then return; fi
    log "Restoring original shim in $TEST_REPO..."

    # Get current SHA (it changed when we installed compiled)
    local current_sha
    current_sha=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent.yml" \
        --jq '.sha' 2>/dev/null || echo "")

    if [[ -z "$current_sha" ]]; then
        err "Could not find agent.yml to restore — manual fix needed!"
        return
    fi

    if gh api "repos/$TEST_REPO/contents/.github/workflows/agent.yml" \
        --method PUT \
        -f message="E2E: restore original shim after pre-release test" \
        -f content="$ORIGINAL_SHIM_CONTENT" \
        -f sha="$current_sha" >/dev/null 2>&1; then
        log "  Original shim restored."
    else
        err "Failed to restore shim — manual fix needed!"
        err "Original content saved in ORIGINAL_SHIM_CONTENT variable"
    fi

    # Remove agent-design.yml if we added it
    local design_sha
    design_sha=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-design.yml" \
        --jq '.sha' 2>/dev/null || echo "")
    if [[ -n "$design_sha" ]]; then
        gh api "repos/$TEST_REPO/contents/.github/workflows/agent-design.yml" \
            -X DELETE \
            -f message="E2E: remove compiled design workflow after pre-release test" \
            -f sha="$design_sha" >/dev/null 2>&1 || true
        log "  Compiled design workflow removed."
    fi

    # Remove agent-review.yml if we added it
    local review_sha
    review_sha=$(gh api "repos/$TEST_REPO/contents/.github/workflows/agent-review.yml" \
        --jq '.sha' 2>/dev/null || echo "")
    if [[ -n "$review_sha" ]]; then
        gh api "repos/$TEST_REPO/contents/.github/workflows/agent-review.yml" \
            -X DELETE \
            -f message="E2E: remove compiled review workflow after pre-release test" \
            -f sha="$review_sha" >/dev/null 2>&1 || true
        log "  Compiled review workflow removed."
    fi
}

cleanup() {
    log "Cleaning up..."
    for issue_num in "${cleanup_issues[@]+"${cleanup_issues[@]}"}"; do
        gh issue close "$issue_num" --repo "$TEST_REPO" --comment "E2E test cleanup" 2>/dev/null || true
    done
    for branch in "${cleanup_branches[@]+"${cleanup_branches[@]}"}"; do
        gh api "repos/$TEST_REPO/git/refs/heads/$branch" -X DELETE 2>/dev/null || true
    done
    if $USE_COMPILED; then
        restore_shim
    fi
    log "Cleanup complete."
}

trap cleanup EXIT

# --- Filter tests ---

active_indices=()
for i in "${!all_names[@]}"; do
    name="${all_names[$i]}"
    provider="${all_providers[$i]}"

    if [[ -n "$FILTER_TEST" && "$name" != "$FILTER_TEST" ]]; then
        continue
    fi
    if [[ -n "$FILTER_PROVIDER" && "$FILTER_PROVIDER" != "all" && "$provider" != "all" && "$provider" != "$FILTER_PROVIDER" ]]; then
        continue
    fi
    active_indices+=("$i")
done

if [[ ${#active_indices[@]} -eq 0 ]]; then
    err "No tests match filters (--test '$FILTER_TEST', --provider '$FILTER_PROVIDER')"
    exit 1
fi

mode="smoke"
$ALL_MODELS && mode="all-models"
if $USE_COMPILED; then
    log "COMPILED MODE: testing compiled workflows (pre-release validation)"
fi
log "Running ${#active_indices[@]} test(s) against branch '$BRANCH' ($mode)"

# --- Install compiled workflow if requested ---

if $USE_COMPILED; then
    install_compiled_workflow
fi

# --- Point e2e-test at target branch ---
# Always reset e2e-test, even when testing main. e2e-test can drift (e.g. stuck at an old
# debug branch) and skipping the reset for main causes tests to run stale code.
log "Setting e2e-test pointer to '$BRANCH'..."
git push origin "$BRANCH:refs/heads/e2e-test" --force-with-lease

# --- Capture baseline run IDs before launching anything ---
# Used to exclude pre-existing runs when matching new workflow runs.
log "Capturing baseline run IDs..."
BASELINE_IDS=$(gh run list --repo "$TEST_REPO" --limit 50 --json databaseId --jq '.[].databaseId' 2>/dev/null || echo "")

is_baseline_id() {
    local id="$1"
    echo "$BASELINE_IDS" | grep -qx "$id"
}

# --- Review + Feedback test state ---
# Review+Feedback is a self-contained test: create issue → resolve → review open PR → feedback resolve.
# The rf-resolve step runs in parallel with the main tests. rf-review and rf-feedback
# resolve) run sequentially after the main polling loop completes.
RF_TS=$(date +%s)
RF_ISSUE_NUM=""
RF_RESOLVE_RUN_ID=""
RF_RESOLVE_RESULT=""
RF_PR_NUM=""
RF_PR_BRANCH=""
RF_INITIAL_SHA=""
# Review step state
RF_REVIEW_RUN_ID=""
RF_REVIEW_RESULT=""
# Feedback step state
RF_FEEDBACK_RUN_ID=""
RF_FEEDBACK_RESULT=""
RF_FEEDBACK_NEW_SHA=""

# --- Create all test issues and trigger all workflows simultaneously ---

# Per-test state for resolve tests (parallel arrays, one entry per active test)
issue_nums=()       # issue number for each active test
test_results=()     # "success", "failure", "cancelled", or "" (pending)
test_run_ids=()     # workflow run ID once found

timestamp=$(date +%s)

log "Creating all resolve test issues..."
for idx in "${active_indices[@]}"; do
    name="${all_names[$idx]}"
    title="${all_titles[$idx]}"
    body="${all_bodies[$idx]}"
    cmd="${all_cmds[$idx]}"

    tag_title="$title (e2e-$timestamp)"
    log "  Creating issue: $tag_title"

    issue_url=$(gh issue create --repo "$TEST_REPO" \
        --title "$tag_title" \
        --body "$body")
    issue_num="${issue_url##*/}"
    issue_nums+=("$issue_num")
    test_results+=("")
    test_run_ids+=("")
    cleanup_issues+=("$issue_num")

    log "  Issue #$issue_num created. Triggering: $cmd"
    gh issue comment "$issue_num" --repo "$TEST_REPO" --body "$cmd"
done

# --- Create review+feedback issue and trigger resolve ---
# Uses a unique e2e-rv-$RF_TS tag so rf runs can be identified unambiguously.
log "Creating review+feedback issue..."
rf_issue_url=$(gh issue create --repo "$TEST_REPO" \
    --title "Test: review+feedback (e2e-rv-$RF_TS)" \
    --body "Add a '## ReviewFeedback' section to README.md containing a Python code block with a function rf_stub() that returns None.")
RF_ISSUE_NUM="${rf_issue_url##*/}"
cleanup_issues+=("$RF_ISSUE_NUM")
log "  Issue #$RF_ISSUE_NUM created. Triggering /agent-resolve..."
gh issue comment "$RF_ISSUE_NUM" --repo "$TEST_REPO" --body "/agent-resolve"

# --- Trigger timeout test ---
log "Creating timeout test issue..."
timeout_ts=$(date +%s)
timeout_title="Test: timeout enforcement (e2e-timeout-$timeout_ts)"
timeout_issue_url=$(gh issue create --repo "$TEST_REPO" \
    --title "$timeout_title" \
    --body "Analyze and refactor every file in this repository to follow best practices, add comprehensive type hints, docstrings, and unit tests. This task is intentionally scope-heavy.")
timeout_issue_num="${timeout_issue_url##*/}"
cleanup_issues+=("$timeout_issue_num")

log "  Issue #$timeout_issue_num. Posting /agent-resolve with timeout_minutes = 5..."
gh issue comment "$timeout_issue_num" --repo "$TEST_REPO" \
    --body $'/agent-resolve\ntimeout_minutes = 5'

TIMEOUT_RUN_ID=""
TIMEOUT_RESULT=""

# Give all workflows a moment to start before polling
log "Waiting 15s for all workflows to start..."
sleep 15

# --- Single polling loop — all tests simultaneously ---
#
# Match runs to tests using displayTitle, which includes the issue/PR title.
# Resolve tests: title contains e2e-$timestamp (unique per run) AND the test's title prefix.
# Review+Feedback resolve: title contains e2e-rv-$RF_TS.
# Timeout test: title contains e2e-timeout-$timeout_ts.
# All non-baseline runs only (exclude pre-existing runs captured above).

log "Polling for workflow completion (timeout: ${TIMEOUT}s)..."

elapsed=0
while [[ $elapsed -lt $TIMEOUT ]]; do
    all_done=true

    # Fetch recent workflow runs once per poll cycle
    run_json=$(gh run list --repo "$TEST_REPO" \
        --limit 50 \
        --json databaseId,status,conclusion,displayTitle 2>/dev/null || echo "[]")

    # --- Poll resolve tests ---
    for pos in "${!issue_nums[@]}"; do
        # Skip already-resolved tests
        if [[ -n "${test_results[$pos]}" ]]; then
            continue
        fi

        name="${all_names[${active_indices[$pos]}]}"
        title="${all_titles[${active_indices[$pos]}]}"
        match_str="e2e-$timestamp"

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            [[ "$conclusion" == "skipped" ]] && continue

            # Skip baseline runs (pre-existing before this e2e run)
            is_baseline_id "$run_id" && continue

            # Match: run title contains our timestamp AND this test's title prefix
            if [[ "$display_title" == *"$match_str"* && "$display_title" == *"$title"* ]]; then
                # Also skip if this run is already claimed by another resolve test
                already_claimed=false
                for other_pos in "${!test_run_ids[@]}"; do
                    if [[ "$other_pos" != "$pos" && "${test_run_ids[$other_pos]}" == "$run_id" ]]; then
                        already_claimed=true
                        break
                    fi
                done
                $already_claimed && continue

                test_run_ids[$pos]="$run_id"
                if [[ "$status" == "completed" ]]; then
                    test_results[$pos]="$conclusion"
                    log "  $name: $conclusion (run $run_id)"
                else
                    log "  $name: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$run_json" | jq -c '.[]')"

        if [[ -z "${test_results[$pos]}" ]]; then
            all_done=false
        fi
    done

    # --- Poll review+feedback resolve ---
    if [[ -z "$RF_RESOLVE_RESULT" ]]; then
        all_done=false

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            [[ "$conclusion" == "skipped" ]] && continue
            is_baseline_id "$run_id" && continue

            if [[ "$display_title" == *"e2e-rv-$RF_TS"* ]]; then
                RF_RESOLVE_RUN_ID="$run_id"
                if [[ "$status" == "completed" ]]; then
                    RF_RESOLVE_RESULT="$conclusion"
                    log "  rf-resolve: $conclusion (run $run_id)"
                    # Locate the PR and capture its initial commit SHA
                    RF_PR_BRANCH="openhands-fix-issue-$RF_ISSUE_NUM"
                    RF_PR_NUM=$(gh pr list --repo "$TEST_REPO" \
                        --search "head:$RF_PR_BRANCH" \
                        --json number --jq '.[0].number // empty' 2>/dev/null || echo "")
                    if [[ -n "$RF_PR_NUM" ]]; then
                        RF_INITIAL_SHA=$(gh api "repos/$TEST_REPO/git/ref/heads/$RF_PR_BRANCH" \
                            --jq '.object.sha' 2>/dev/null || echo "")
                        cleanup_branches+=("$RF_PR_BRANCH")
                        log "  rf-resolve: PR #$RF_PR_NUM branch $RF_PR_BRANCH (SHA ${RF_INITIAL_SHA:0:7})"
                    fi
                else
                    log "  rf-resolve: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$run_json" | jq -c '.[]')"
    fi

    # --- Poll timeout test ---
    if [[ -z "$TIMEOUT_RESULT" ]]; then
        all_done=false

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            [[ "$conclusion" == "skipped" ]] && continue
            is_baseline_id "$run_id" && continue

            if [[ "$display_title" == *"e2e-timeout-$timeout_ts"* ]]; then
                TIMEOUT_RUN_ID="$run_id"
                if [[ "$status" == "completed" ]]; then
                    TIMEOUT_RESULT="$conclusion"
                    log "  timeout-test: $conclusion (run $run_id)"
                else
                    log "  timeout-test: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$run_json" | jq -c '.[]')"
    fi

    if $all_done; then
        break
    fi

    log "  Waiting... (${elapsed}s elapsed)"
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

# --- Review step (sequential, after main polling loop) ---
# Post /agent-review on the open PR created by rf-resolve.
# Capture a new baseline first so rf-resolve's run ID is excluded.

if [[ "$RF_RESOLVE_RESULT" == "success" && -n "$RF_PR_NUM" ]]; then
    log ""
    log "rf-review: Posting /agent-review on PR #$RF_PR_NUM..."
    RF_REVIEW_BASELINE=$(gh run list --repo "$TEST_REPO" --limit 50 --json databaseId \
        --jq '.[].databaseId' 2>/dev/null || echo "")

    gh pr comment "$RF_PR_NUM" --repo "$TEST_REPO" --body "/agent-review"

    rf_review_elapsed=0
    RF_REVIEW_TIMEOUT=1200  # 20 minutes

    while [[ $rf_review_elapsed -lt $RF_REVIEW_TIMEOUT && -z "$RF_REVIEW_RESULT" ]]; do
        rf_review_json=$(gh run list --repo "$TEST_REPO" --limit 50 \
            --json databaseId,status,conclusion,displayTitle 2>/dev/null || echo "[]")

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            [[ "$conclusion" == "skipped" ]] && continue
            echo "$RF_REVIEW_BASELINE" | grep -qx "$run_id" && continue

            if [[ "$display_title" == *"e2e-rv-$RF_TS"* ]]; then
                RF_REVIEW_RUN_ID="$run_id"
                if [[ "$status" == "completed" ]]; then
                    RF_REVIEW_RESULT="$conclusion"
                    log "  rf-review: $conclusion (run $run_id)"
                else
                    log "  rf-review: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$rf_review_json" | jq -c '.[]')"

        if [[ -z "$RF_REVIEW_RESULT" ]]; then
            log "  rf-review: waiting... (${rf_review_elapsed}s)"
            sleep "$POLL_INTERVAL"
            rf_review_elapsed=$((rf_review_elapsed + POLL_INTERVAL))
        fi
    done
fi

# --- Feedback step (sequential, after rf-review) ---
# Post a feedback comment + /agent-resolve on the PR, then wait for a new commit.
# Capture a new baseline so rf-review's run ID is excluded.

if [[ "$RF_REVIEW_RESULT" == "success" && -n "$RF_PR_NUM" ]]; then
    log ""
    log "rf-feedback: Posting feedback + /agent-resolve on PR #$RF_PR_NUM..."
    RF_FEEDBACK_BASELINE=$(gh run list --repo "$TEST_REPO" --limit 50 --json databaseId \
        --jq '.[].databaseId' 2>/dev/null || echo "")

    # Post feedback first, then trigger resolve
    gh pr comment "$RF_PR_NUM" --repo "$TEST_REPO" \
        --body "Please update rf_stub() to return the string 'hello world' instead of None."
    sleep 2
    gh pr comment "$RF_PR_NUM" --repo "$TEST_REPO" --body "/agent-resolve"

    rf_feedback_elapsed=0
    RF_FEEDBACK_TIMEOUT=1200  # 20 minutes

    while [[ $rf_feedback_elapsed -lt $RF_FEEDBACK_TIMEOUT && -z "$RF_FEEDBACK_RESULT" ]]; do
        rf_feedback_json=$(gh run list --repo "$TEST_REPO" --limit 50 \
            --json databaseId,status,conclusion,displayTitle 2>/dev/null || echo "[]")

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            [[ "$conclusion" == "skipped" ]] && continue
            echo "$RF_FEEDBACK_BASELINE" | grep -qx "$run_id" && continue

            if [[ "$display_title" == *"e2e-rv-$RF_TS"* ]]; then
                RF_FEEDBACK_RUN_ID="$run_id"
                if [[ "$status" == "completed" ]]; then
                    RF_FEEDBACK_RESULT="$conclusion"
                    log "  rf-feedback: $conclusion (run $run_id)"
                    # Check whether the branch has a new commit
                    RF_FEEDBACK_NEW_SHA=$(gh api "repos/$TEST_REPO/git/ref/heads/$RF_PR_BRANCH" \
                        --jq '.object.sha' 2>/dev/null || echo "")
                else
                    log "  rf-feedback: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$rf_feedback_json" | jq -c '.[]')"

        if [[ -z "$RF_FEEDBACK_RESULT" ]]; then
            log "  rf-feedback: waiting... (${rf_feedback_elapsed}s)"
            sleep "$POLL_INTERVAL"
            rf_feedback_elapsed=$((rf_feedback_elapsed + POLL_INTERVAL))
        fi
    done
fi

# --- Verify results ---

log ""
log "========================================="
if $USE_COMPILED; then
    log "  E2E Test Results (COMPILED)"
else
    log "  E2E Test Results"
fi
log "========================================="

pass=0
fail=0
timeout_count=0

# --- Resolve / design test results ---
for pos in "${!issue_nums[@]}"; do
    idx="${active_indices[$pos]}"
    name="${all_names[$idx]}"
    test_type="${all_types[$idx]}"
    issue_num="${issue_nums[$pos]}"
    conclusion="${test_results[$pos]:-timeout}"
    run_id="${test_run_ids[$pos]}"

    if [[ "$conclusion" == "success" ]]; then
        if [[ "$test_type" == "design" ]]; then
            # Design mode: check if a comment was posted (not a PR)
            comment_count=$(gh api "repos/$TEST_REPO/issues/$issue_num/comments" \
                --jq '[.[] | select(.body | contains("Design analysis"))] | length' \
                2>/dev/null || echo "0")
            if [[ "$comment_count" -gt 0 ]]; then
                status="PASS (comment posted)"
            else
                status="PASS (no comment found)"
            fi
            ((pass++)) || true
        elif [[ "$test_type" == "explore" ]]; then
            # Explore mode: check if an analysis comment was posted
            comment_count=$(gh api "repos/$TEST_REPO/issues/$issue_num/comments" \
                --jq '[.[] | select(.body | contains("Exploration by"))] | length' \
                2>/dev/null || echo "0")
            if [[ "$comment_count" -gt 0 ]]; then
                status="PASS (analysis posted)"
            else
                status="PASS (no analysis found)"
            fi
            ((pass++)) || true
        else
            # Resolve mode: check if a PR was created
            pr_count=$(gh pr list --repo "$TEST_REPO" \
                --search "head:openhands-fix-issue-$issue_num" \
                --json number --jq 'length' 2>/dev/null || echo "0")

            if [[ "$pr_count" -gt 0 ]]; then
                status="PASS"
                ((pass++)) || true
                cleanup_branches+=("openhands-fix-issue-$issue_num")
            else
                status="PASS (no PR)"
                ((pass++)) || true
            fi
        fi
    elif [[ "$conclusion" == "timeout" ]]; then
        status="TIMEOUT"
        ((timeout_count++)) || true
    else
        status="FAIL ($conclusion)"
        ((fail++)) || true
    fi

    # Build clickable job log URL
    log_url=""
    if [[ -n "$run_id" ]]; then
        log_url="https://github.com/$TEST_REPO/actions/runs/$run_id"
    fi

    printf "  %-25s %-30s issue #%-5s %s\n" "$name" "$status" "$issue_num" "$log_url"
done

# --- Review + Feedback results ---
log ""
log "--- Review + Feedback Test ---"

RF_PASS=0
RF_FAIL=0
rf_pr_ref="${RF_PR_NUM:-N/A}"

# rf-resolve result
rf_resolve_url=""
[[ -n "$RF_RESOLVE_RUN_ID" ]] && rf_resolve_url="https://github.com/$TEST_REPO/actions/runs/$RF_RESOLVE_RUN_ID"
if [[ -z "$RF_RESOLVE_RESULT" ]]; then
    rf_resolve_status="TIMEOUT"
    ((RF_FAIL++)) || true
elif [[ "$RF_RESOLVE_RESULT" == "success" ]]; then
    if [[ -n "$RF_PR_NUM" ]]; then
        rf_resolve_status="PASS (PR #$RF_PR_NUM)"
    else
        rf_resolve_status="PASS (no PR found)"
    fi
    ((RF_PASS++)) || true
else
    rf_resolve_status="FAIL ($RF_RESOLVE_RESULT)"
    ((RF_FAIL++)) || true
fi
printf "  %-25s %-30s issue #%-5s %s\n" "rf-resolve" "$rf_resolve_status" "${RF_ISSUE_NUM:-N/A}" "$rf_resolve_url"

# rf-review result
rf_review_url=""
[[ -n "$RF_REVIEW_RUN_ID" ]] && rf_review_url="https://github.com/$TEST_REPO/actions/runs/$RF_REVIEW_RUN_ID"
if [[ "$RF_RESOLVE_RESULT" != "success" || -z "$RF_PR_NUM" ]]; then
    rf_review_status="SKIPPED (resolve didn't create PR)"
elif [[ -z "$RF_REVIEW_RESULT" ]]; then
    rf_review_status="TIMEOUT"
    ((RF_FAIL++)) || true
elif [[ "$RF_REVIEW_RESULT" == "success" ]]; then
    comment_count=$(gh api "repos/$TEST_REPO/issues/$RF_PR_NUM/comments" \
        --jq '[.[] | select(.body | contains("Code review by"))] | length' \
        2>/dev/null || echo "0")
    if [[ "$comment_count" -gt 0 ]]; then
        rf_review_status="PASS (review comment posted)"
    else
        rf_review_status="PASS (no review comment found)"
    fi
    ((RF_PASS++)) || true
else
    rf_review_status="FAIL ($RF_REVIEW_RESULT)"
    ((RF_FAIL++)) || true
fi
printf "  %-25s %-30s PR #%-5s  %s\n" "rf-review" "$rf_review_status" "$rf_pr_ref" "$rf_review_url"

# rf-feedback result
rf_feedback_url=""
[[ -n "$RF_FEEDBACK_RUN_ID" ]] && rf_feedback_url="https://github.com/$TEST_REPO/actions/runs/$RF_FEEDBACK_RUN_ID"
if [[ "$RF_REVIEW_RESULT" != "success" || -z "$RF_PR_NUM" ]]; then
    rf_feedback_status="SKIPPED (review didn't complete)"
elif [[ -z "$RF_FEEDBACK_RESULT" ]]; then
    rf_feedback_status="TIMEOUT"
    ((RF_FAIL++)) || true
elif [[ "$RF_FEEDBACK_RESULT" == "success" ]]; then
    if [[ -n "$RF_FEEDBACK_NEW_SHA" && -n "$RF_INITIAL_SHA" && "$RF_FEEDBACK_NEW_SHA" != "$RF_INITIAL_SHA" ]]; then
        rf_feedback_status="PASS (new commit on branch)"
    else
        rf_feedback_status="PASS (no new commit detected)"
    fi
    ((RF_PASS++)) || true
else
    rf_feedback_status="FAIL ($RF_FEEDBACK_RESULT)"
    ((RF_FAIL++)) || true
fi
printf "  %-25s %-30s PR #%-5s  %s\n" "rf-feedback" "$rf_feedback_status" "$rf_pr_ref" "$rf_feedback_url"

# --- Timeout test result ---
log ""
log "--- Timeout Test ---"

TIMEOUT_PHASE_PASS=0
TIMEOUT_PHASE_FAIL=0

timeout_log_url=""
[[ -n "$TIMEOUT_RUN_ID" ]] && timeout_log_url="https://github.com/$TEST_REPO/actions/runs/$TIMEOUT_RUN_ID"

if [[ -z "$TIMEOUT_RESULT" ]]; then
    timeout_status="TIMEOUT (e2e wait exceeded)"
    ((TIMEOUT_PHASE_FAIL++)) || true
elif [[ "$TIMEOUT_RESULT" == "success" || "$TIMEOUT_RESULT" == "failure" ]]; then
    # Both success and failure are valid: the watchdog kills OpenHands (making the
    # resolver step exit non-zero → job conclusion = failure), but cleanup steps
    # still run due to if:always(). Accept either conclusion as "run completed".
    comment_count=$(gh api "repos/$TEST_REPO/issues/$timeout_issue_num/comments" \
        --jq '[.[] | select(.body | contains("could not fully resolve") or contains("exited unexpectedly"))] | length' \
        2>/dev/null || echo "0")
    if [[ "$comment_count" -gt 0 ]]; then
        timeout_status="PASS (watchdog fired + comment posted) [${TIMEOUT_RESULT}]"
        ((TIMEOUT_PHASE_PASS++)) || true
    else
        timeout_status="PASS (run completed, no comment found) [${TIMEOUT_RESULT}]"
        ((TIMEOUT_PHASE_PASS++)) || true
    fi
else
    timeout_status="FAIL ($TIMEOUT_RESULT)"
    ((TIMEOUT_PHASE_FAIL++)) || true
fi

printf "  %-25s %-30s issue #%-5s %s\n" "timeout" "$timeout_status" "$timeout_issue_num" "$timeout_log_url"

# --- Collect costs from all tests ---
log ""
log "--- Cost Collection ---"

total_cost=0.00
cost_count=0

# Collect costs from resolve/design test issues
for pos in "${!issue_nums[@]}"; do
    idx="${active_indices[$pos]}"
    name="${all_names[$idx]}"
    issue_num="${issue_nums[$pos]}"

    # Fetch cost comment from the issue
    cost_comment=$(gh api "repos/$TEST_REPO/issues/$issue_num/comments" \
        --jq '[.[] | select(.body | contains("Cost Summary"))] | last | .body' \
        2>/dev/null || echo "")

    if [[ -n "$cost_comment" ]]; then
        cost=$(parse_cost_from_comment "$cost_comment")
        if [[ -n "$cost" && "$cost" != "0.00" ]]; then
            total_cost=$(python3 -c "print(f'{$total_cost + $cost:.2f}')")
            ((cost_count++)) || true
            printf "  %-25s \$%s\n" "$name" "$cost"
        else
            printf "  %-25s (no cost data)\n" "$name"
        fi
    else
        printf "  %-25s (no cost comment)\n" "$name"
    fi
done

# Collect cost from rf-resolve (issue comments)
if [[ -n "$RF_ISSUE_NUM" ]]; then
    cost_comment=$(gh api "repos/$TEST_REPO/issues/$RF_ISSUE_NUM/comments" \
        --jq '[.[] | select(.body | contains("Cost Summary"))] | last | .body' \
        2>/dev/null || echo "")
    if [[ -n "$cost_comment" ]]; then
        cost=$(parse_cost_from_comment "$cost_comment")
        if [[ -n "$cost" && "$cost" != "0.00" ]]; then
            total_cost=$(python3 -c "print(f'{$total_cost + $cost:.2f}')")
            ((cost_count++)) || true
            printf "  %-25s \$%s\n" "rf-resolve" "$cost"
        else
            printf "  %-25s (no cost data)\n" "rf-resolve"
        fi
    else
        printf "  %-25s (no cost comment)\n" "rf-resolve"
    fi
fi

# Collect costs from rf-review and rf-feedback (PR comments)
if [[ -n "$RF_PR_NUM" ]]; then
    cost_comment=$(gh api "repos/$TEST_REPO/issues/$RF_PR_NUM/comments" \
        --jq '[.[] | select(.body | contains("Cost Summary"))] | last | .body' \
        2>/dev/null || echo "")
    if [[ -n "$cost_comment" ]]; then
        cost=$(parse_cost_from_comment "$cost_comment")
        if [[ -n "$cost" && "$cost" != "0.00" ]]; then
            total_cost=$(python3 -c "print(f'{$total_cost + $cost:.2f}')")
            ((cost_count++)) || true
            printf "  %-25s \$%s\n" "rf-review+feedback" "$cost"
        else
            printf "  %-25s (no cost data)\n" "rf-review+feedback"
        fi
    else
        printf "  %-25s (no cost comment)\n" "rf-review+feedback"
    fi
fi

# Collect cost from timeout test
cost_comment=$(gh api "repos/$TEST_REPO/issues/$timeout_issue_num/comments" \
    --jq '[.[] | select(.body | contains("Cost Summary"))] | last | .body' \
    2>/dev/null || echo "")

if [[ -n "$cost_comment" ]]; then
    cost=$(parse_cost_from_comment "$cost_comment")
    if [[ -n "$cost" && "$cost" != "0.00" ]]; then
        total_cost=$(python3 -c "print(f'{$total_cost + $cost:.2f}')")
        ((cost_count++)) || true
        printf "  %-25s \$%s\n" "timeout" "$cost"
    else
        printf "  %-25s (no cost data)\n" "timeout"
    fi
else
    printf "  %-25s (no cost comment)\n" "timeout"
fi

log ""
log "  Total cost: \$$total_cost ($cost_count tests with cost data)"

# --- Summary ---
log ""
log "========================================="
log "  Resolve/Design: Pass: $pass  Fail: $fail  Timeout: $timeout_count"
log "  Review+Feedback:  Pass: $RF_PASS  Fail: $RF_FAIL"
log "  Timeout test:   Pass: $TIMEOUT_PHASE_PASS  Fail: $TIMEOUT_PHASE_FAIL"
log "  Total cost:     \$$total_cost"
log "========================================="

# Exit with failure if any test didn't pass
total_fail=$((fail + timeout_count + RF_FAIL + TIMEOUT_PHASE_FAIL))
if [[ $total_fail -gt 0 ]]; then
    exit 1
fi
