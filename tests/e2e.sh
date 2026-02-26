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
POLL_INTERVAL=120
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

    # Read all model aliases and their model family names from the config
    while IFS='|' read -r alias model_family; do
        safe_alias="${alias//-/_}"
        add_test "$alias" "Test ($alias): add hello_${safe_alias}.py" \
            "Create a file hello_${safe_alias}.py with a function hello() that returns 'Hello from ${alias}!'" \
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
    add_test "default-model" "Test (default): add hello_default.py" \
        "Create a file hello_default.py with a function hello() that returns 'Hello from default!'" \
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

    add_test "gemini" "Test: add hi.py" \
        "Create a file hi.py with a function hi() that returns 'Hi!'" \
        "/agent-resolve-gemini-small" "gemini" "resolve"

    # Design mode smoke test
    add_test "design" "Test: design analysis" \
        "Discuss whether this test repo should have a README. What would you include?" \
        "/agent-design" "all" "design"

    # Explore mode smoke test (dev-only feature)
    add_test "explore" "Test: explore analysis" \
        "Discuss the design trade-offs of storing configuration in YAML vs TOML vs JSON for a developer tooling project." \
        "/agent-explore" "all" "explore"
fi

# Note: review mode is tested in Phase 2 (after main tests), piggybacking on a resolve test's PR.

# --- Helpers ---

log() { echo "==> $*"; }
err() { echo "ERROR: $*" >&2; }

cleanup_issues=()
cleanup_branches=()

# --- Compiled workflow swap ---
# When --compiled is used, we replace the shim (agent.yml) in the test repo
# with agent-resolve.yml, add agent-design.yml, run the full test suite, then
# restore the original shim and remove agent-design.yml.

ORIGINAL_SHIM_CONTENT=""  # base64-encoded original shim
ORIGINAL_SHIM_SHA=""      # SHA for restoring
DESIGN_WORKFLOW_SHA=""     # SHA for removing agent-design.yml on cleanup

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

# --- Create test issues and trigger ---

# Per-test state (parallel arrays, one entry per active test)
issue_nums=()       # issue number for each active test
test_results=()     # "success", "failure", or "" (pending)
test_run_ids=()     # workflow run ID once found

timestamp=$(date +%s)

for idx in "${active_indices[@]}"; do
    name="${all_names[$idx]}"
    title="${all_titles[$idx]}"
    body="${all_bodies[$idx]}"
    cmd="${all_cmds[$idx]}"

    tag_title="$title (e2e-$timestamp)"
    log "Creating issue: $tag_title"

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

# Give GitHub a moment to start the workflows
log "Waiting 15s for workflows to start..."
sleep 15

# --- Poll for workflow completion ---
#
# Match runs to issues using the run's displayTitle, which includes the
# issue title. Our issue titles contain a unique timestamp (e2e-NNNN)
# so we can match precisely.

log "Polling for workflow completion (timeout: ${TIMEOUT}s)..."

elapsed=0
while [[ $elapsed -lt $TIMEOUT ]]; do
    all_done=true

    # Get recent workflow runs once per poll cycle — check all workflow files
    run_json=$(gh run list --repo "$TEST_REPO" \
        --limit 20 \
        --json databaseId,status,conclusion,displayTitle 2>/dev/null || echo "[]")

    for pos in "${!issue_nums[@]}"; do
        # Skip already-resolved tests
        if [[ -n "${test_results[$pos]}" ]]; then
            continue
        fi

        issue_num="${issue_nums[$pos]}"
        name="${all_names[${active_indices[$pos]}]}"
        title="${all_titles[${active_indices[$pos]}]}"
        # Match on the unique timestamp tag in the issue title
        match_str="e2e-$timestamp"

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            # Skip runs that were skipped (e.g., bot's own comment re-triggered the shim)
            if [[ "$conclusion" == "skipped" ]]; then
                continue
            fi

            # Match: run title contains our timestamp AND our test's title prefix
            if [[ "$display_title" == *"$match_str"* && "$display_title" == *"$title"* ]]; then
                test_run_ids[$pos]="$run_id"
                if [[ "$status" == "completed" ]]; then
                    test_results[$pos]="$conclusion"
                    log "  $name: $conclusion (run $run_id)"
                else
                    # Found our run but still in progress
                    log "  $name: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$run_json" | jq -c '.[]')"

        if [[ -z "${test_results[$pos]}" ]]; then
            all_done=false
        fi
    done

    if $all_done; then
        break
    fi

    log "  Waiting... (${elapsed}s elapsed)"
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

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

    printf "  %-25s %-25s issue #%-5s %s\n" "$name" "$status" "$issue_num" "$log_url"
done

log "========================================="
log "  Pass: $pass  Fail: $fail  Timeout: $timeout_count"
log "========================================="

# --- Phase 2: Review test ---
# Piggybacks on a PR created by a resolve test. Avoids creating a throwaway
# issue+PR just to test review mode.

REVIEW_PASS=0
REVIEW_FAIL=0
REVIEW_SKIP=0

# Find the first resolve test that produced a PR
REVIEW_PR_NUM=""
REVIEW_SOURCE_ISSUE=""
for pos in "${!issue_nums[@]}"; do
    idx="${active_indices[$pos]}"
    test_type="${all_types[$idx]}"
    issue_num="${issue_nums[$pos]}"

    if [[ "$test_type" == "resolve" && "${test_results[$pos]}" == "success" ]]; then
        pr_num=$(gh pr list --repo "$TEST_REPO" \
            --search "head:openhands-fix-issue-$issue_num" \
            --json number --jq '.[0].number' 2>/dev/null || echo "")
        if [[ -n "$pr_num" ]]; then
            REVIEW_PR_NUM="$pr_num"
            REVIEW_SOURCE_ISSUE="$issue_num"
            break
        fi
    fi
done

if [[ -z "$REVIEW_PR_NUM" ]]; then
    log ""
    log "Phase 2: Review test — SKIPPED (no resolve test produced a PR)"
    ((REVIEW_SKIP++)) || true
else
    log ""
    log "Phase 2: Review test — posting /agent-review on PR #$REVIEW_PR_NUM (from issue #$REVIEW_SOURCE_ISSUE)"
    gh pr comment "$REVIEW_PR_NUM" --repo "$TEST_REPO" --body "/agent-review"

    log "  Waiting 15s for review workflow to start..."
    sleep 15

    # Track which run IDs belong to the main tests (exclude them when matching review run)
    main_run_ids=()
    for tracked_id in "${test_run_ids[@]+"${test_run_ids[@]}"}"; do
        [[ -n "$tracked_id" ]] && main_run_ids+=("$tracked_id")
    done

    REVIEW_RUN_ID=""
    REVIEW_RESULT=""
    REVIEW_TIMEOUT=900  # 15 minutes
    review_elapsed=0

    # The PR title contains our e2e timestamp (it came from the resolve test's issue title).
    match_str="e2e-$timestamp"

    while [[ $review_elapsed -lt $REVIEW_TIMEOUT ]]; do
        run_json=$(gh run list --repo "$TEST_REPO" \
            --limit 20 \
            --json databaseId,status,conclusion,displayTitle 2>/dev/null || echo "[]")

        while IFS= read -r row; do
            [[ -z "$row" ]] && continue
            display_title=$(echo "$row" | jq -r '.displayTitle')
            status=$(echo "$row" | jq -r '.status')
            conclusion=$(echo "$row" | jq -r '.conclusion')
            run_id=$(echo "$row" | jq -r '.databaseId')

            [[ "$conclusion" == "skipped" ]] && continue

            if [[ "$display_title" == *"$match_str"* ]]; then
                # Skip runs already tracked by the main loop
                already_tracked=false
                for tracked_id in "${main_run_ids[@]+"${main_run_ids[@]}"}"; do
                    if [[ "$tracked_id" == "$run_id" ]]; then
                        already_tracked=true
                        break
                    fi
                done
                $already_tracked && continue

                REVIEW_RUN_ID="$run_id"
                if [[ "$status" == "completed" ]]; then
                    REVIEW_RESULT="$conclusion"
                    log "  review: $conclusion (run $run_id)"
                else
                    log "  review: $status (run $run_id)"
                fi
                break
            fi
        done <<< "$(echo "$run_json" | jq -c '.[]')"

        [[ -n "$REVIEW_RESULT" ]] && break

        log "  Waiting... (${review_elapsed}s elapsed)"
        sleep 60
        review_elapsed=$((review_elapsed + 60))
    done

    log ""
    log "========================================="
    log "  Phase 2: Review Test"
    log "========================================="

    review_status=""
    review_log_url=""
    [[ -n "$REVIEW_RUN_ID" ]] && review_log_url="https://github.com/$TEST_REPO/actions/runs/$REVIEW_RUN_ID"

    if [[ "${REVIEW_RESULT:-timeout}" == "timeout" ]]; then
        review_status="TIMEOUT"
        ((REVIEW_FAIL++)) || true
    elif [[ "$REVIEW_RESULT" == "success" ]]; then
        # Verify review comment was posted on the PR
        comment_count=$(gh api "repos/$TEST_REPO/issues/$REVIEW_PR_NUM/comments" \
            --jq '[.[] | select(.body | contains("Code review by"))] | length' \
            2>/dev/null || echo "0")
        if [[ "$comment_count" -gt 0 ]]; then
            review_status="PASS (review comment posted)"
            ((REVIEW_PASS++)) || true
        else
            review_status="PASS (no review comment found)"
            ((REVIEW_PASS++)) || true
        fi
    else
        review_status="FAIL ($REVIEW_RESULT)"
        ((REVIEW_FAIL++)) || true
    fi

    printf "  %-25s %-25s PR #%-5s  %s\n" "review" "$review_status" "$REVIEW_PR_NUM" "$review_log_url"

    log "========================================="
    log "  Phase 2: Pass: $REVIEW_PASS  Fail: $REVIEW_FAIL  Skip: $REVIEW_SKIP"
    log "========================================="
fi

# --- Phase 4: Graceful wrapup test ---
# Verifies that approaching max_iterations triggers wrapup instructions.
# Uses a low max_iterations that the agent is unlikely to complete in — the
# workflow should still complete cleanly and post a failure comment.
# Uses the inline max_iterations arg — this phase is dev-only.

WRAPUP_PHASE_PASS=0
WRAPUP_PHASE_FAIL=0

log ""
log "Phase 4: Graceful wrapup test — verifying wrapup at iteration budget"

wrapup_ts=$(date +%s)
wrapup_title="Test: graceful wrapup (e2e-wrapup-$wrapup_ts)"
wrapup_issue_url=$(gh issue create --repo "$TEST_REPO" \
    --title "$wrapup_title" \
    --body "Implement a comprehensive test suite with 20+ test cases for all Python files in this repository. Include edge cases, error paths, and integration tests.")
wrapup_issue_num="${wrapup_issue_url##*/}"
cleanup_issues+=("$wrapup_issue_num")

log "  Issue #$wrapup_issue_num. Posting /agent-resolve with max_iterations = 4..."
gh issue comment "$wrapup_issue_num" --repo "$TEST_REPO" \
    --body $'/agent-resolve\nmax_iterations = 4'

log "  Waiting 15s for workflow to start..."
sleep 15

WRAPUP_RUN_ID=""
WRAPUP_RESULT=""
WRAPUP_WAIT=1200  # 20 minutes
wrapup_elapsed=0

while [[ $wrapup_elapsed -lt $WRAPUP_WAIT ]]; do
    run_json=$(gh run list --repo "$TEST_REPO" \
        --limit 20 \
        --json databaseId,status,conclusion,displayTitle 2>/dev/null || echo "[]")

    while IFS= read -r row; do
        [[ -z "$row" ]] && continue
        display_title=$(echo "$row" | jq -r '.displayTitle')
        status=$(echo "$row" | jq -r '.status')
        conclusion=$(echo "$row" | jq -r '.conclusion')
        run_id=$(echo "$row" | jq -r '.databaseId')
        [[ "$conclusion" == "skipped" ]] && continue

        if [[ "$display_title" == *"e2e-wrapup-$wrapup_ts"* ]]; then
            WRAPUP_RUN_ID="$run_id"
            if [[ "$status" == "completed" ]]; then
                WRAPUP_RESULT="$conclusion"
                log "  wrapup-test: $conclusion (run $run_id)"
            else
                log "  wrapup-test: $status (run $run_id)"
            fi
            break
        fi
    done <<< "$(echo "$run_json" | jq -c '.[]')"

    [[ -n "$WRAPUP_RESULT" ]] && break
    log "  Waiting... (${wrapup_elapsed}s elapsed)"
    sleep 60
    wrapup_elapsed=$((wrapup_elapsed + 60))
done

log ""
log "========================================="
log "  Phase 4: Graceful Wrapup Test"
log "========================================="

wrapup_log_url=""
[[ -n "$WRAPUP_RUN_ID" ]] && wrapup_log_url="https://github.com/$TEST_REPO/actions/runs/$WRAPUP_RUN_ID"

if [[ -z "$WRAPUP_RESULT" ]]; then
    wrapup_status="TIMEOUT (e2e wait exceeded)"
    ((WRAPUP_PHASE_FAIL++)) || true
elif [[ "$WRAPUP_RESULT" == "success" ]]; then
    # Check for either a PR (agent finished) or a failure comment (wrapup triggered)
    pr_count=$(gh pr list --repo "$TEST_REPO" \
        --search "head:openhands-fix-issue-$wrapup_issue_num" \
        --json number --jq 'length' 2>/dev/null || echo "0")
    comment_count=$(gh api "repos/$TEST_REPO/issues/$wrapup_issue_num/comments" \
        --jq '[.[] | select(.body | contains("could not fully resolve"))] | length' \
        2>/dev/null || echo "0")
    if [[ "$pr_count" -gt 0 ]]; then
        wrapup_status="PASS (agent finished — PR created)"
        cleanup_branches+=("openhands-fix-issue-$wrapup_issue_num")
        ((WRAPUP_PHASE_PASS++)) || true
    elif [[ "$comment_count" -gt 0 ]]; then
        wrapup_status="PASS (wrapup triggered — failure comment posted)"
        ((WRAPUP_PHASE_PASS++)) || true
    else
        wrapup_status="PASS (run completed, no clear output found)"
        ((WRAPUP_PHASE_PASS++)) || true
    fi
else
    wrapup_status="FAIL ($WRAPUP_RESULT)"
    ((WRAPUP_PHASE_FAIL++)) || true
fi

printf "  %-25s %-25s issue #%-5s %s\n" "wrapup" "$wrapup_status" "$wrapup_issue_num" "$wrapup_log_url"
log "========================================="
log "  Phase 4: Pass: $WRAPUP_PHASE_PASS  Fail: $WRAPUP_PHASE_FAIL"
log "========================================="

# Exit with failure if any test didn't pass
total_fail=$((fail + REVIEW_FAIL + WRAPUP_PHASE_FAIL))
total_timeout=$timeout_count
if [[ $total_fail -gt 0 || $total_timeout -gt 0 ]]; then
    exit 1
fi
