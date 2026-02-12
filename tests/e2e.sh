#!/usr/bin/env bash
# E2E tests for remote-dev-bot.
#
# Creates test issues in remote-dev-bot-test, triggers the agent,
# waits for workflow completion, and verifies results.
#
# Usage:
#   ./tests/e2e.sh [--branch <branch>] [--test <name>] [--provider <name>]
#                  [--all-models]
#
#   --branch      Branch to test (default: main). Sets dev pointer to this branch.
#   --test        Run a specific test only (default: all)
#   --provider    Run only tests for a specific provider (claude/openai/gemini)
#   --all-models  Test every model alias, not just one per provider

set -euo pipefail

TEST_REPO="gnovak/remote-dev-bot-test"
POLL_INTERVAL=60
TIMEOUT=900  # 15 minutes

# --- Argument parsing ---

BRANCH="main"
FILTER_TEST=""
FILTER_PROVIDER=""
ALL_MODELS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --branch) BRANCH="$2"; shift 2 ;;
        --test) FILTER_TEST="$2"; shift 2 ;;
        --provider) FILTER_PROVIDER="$2"; shift 2 ;;
        --all-models) ALL_MODELS=true; shift ;;
        -h|--help)
            head -14 "$0" | tail -10
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Test case definitions ---
# Parallel arrays — index i corresponds to the same test across all arrays.

all_names=()
all_titles=()
all_bodies=()
all_cmds=()
all_providers=()

add_test() {
    all_names+=("$1"); all_titles+=("$2"); all_bodies+=("$3")
    all_cmds+=("$4"); all_providers+=("$5")
}

if $ALL_MODELS; then
    # Generate a test for every model alias in the config file.
    # Requires PyYAML (pip install PyYAML).
    config_file="remote-dev-bot.yaml"
    if [[ ! -f "$config_file" ]]; then
        echo "ERROR: $config_file not found. Run from repo root." >&2
        exit 1
    fi

    # Read all model aliases and their provider prefixes from the config
    while IFS='|' read -r alias provider; do
        # Sanitize alias for use in filenames: claude-small -> claude_small
        safe_alias="${alias//-/_}"
        add_test "$alias" "Test ($alias): add hello_${safe_alias}.py" \
            "Create a file hello_${safe_alias}.py with a function hello() that returns 'Hello from ${alias}!'" \
            "/agent-$alias" "$provider"
    done < <(python3 -c "
import yaml, sys
with open('$config_file') as f:
    config = yaml.safe_load(f)
for alias, info in config.get('models', {}).items():
    model_id = info.get('id', '')
    provider = model_id.split('/')[0] if '/' in model_id else 'unknown'
    print(f'{alias}|{provider}')
")

    # Also add the default-model test (uses /agent with no alias)
    add_test "default-model" "Test (default): add hello_default.py" \
        "Create a file hello_default.py with a function hello() that returns 'Hello from default!'" \
        "/agent" "all"
else
    # Smoke tests: one small model per provider + default alias
    add_test "default-model" "Test: add hello.py" \
        "Create a file hello.py with a function hello() that returns 'Hello, world!'" \
        "/agent" "all"

    add_test "claude" "Test: add greet.py" \
        "Create a file greet.py with a function greet(name) that returns f'Hello, {name}!'" \
        "/agent-claude-small" "claude"

    add_test "openai" "Test: add wave.py" \
        "Create a file wave.py with a function wave() that returns 'Wave!'" \
        "/agent-openai-small" "openai"

    add_test "gemini" "Test: add hi.py" \
        "Create a file hi.py with a function hi() that returns 'Hi!'" \
        "/agent-gemini-small" "gemini"
fi

# --- Helpers ---

log() { echo "==> $*"; }
err() { echo "ERROR: $*" >&2; }

cleanup_issues=()
cleanup_branches=()

cleanup() {
    log "Cleaning up..."
    for issue_num in "${cleanup_issues[@]+"${cleanup_issues[@]}"}"; do
        gh issue close "$issue_num" --repo "$TEST_REPO" --comment "E2E test cleanup" 2>/dev/null || true
    done
    for branch in "${cleanup_branches[@]+"${cleanup_branches[@]}"}"; do
        gh api "repos/$TEST_REPO/git/refs/heads/$branch" -X DELETE 2>/dev/null || true
    done
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
log "Running ${#active_indices[@]} test(s) against branch '$BRANCH' ($mode)"

# --- Point dev at target branch ---

if [[ "$BRANCH" != "main" ]]; then
    log "Setting dev pointer to '$BRANCH'..."
    git push origin "$BRANCH:refs/heads/dev" --force-with-lease
fi

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

    # Get recent workflow runs once per poll cycle
    run_json=$(gh run list --repo "$TEST_REPO" \
        --workflow=agent.yml \
        --limit 50 \
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

            # Match: run title contains our timestamp AND our test's title prefix
            if [[ "$display_title" == *"$match_str"* && "$display_title" == *"$title"* ]]; then
                if [[ "$status" == "completed" ]]; then
                    test_results[$pos]="$conclusion"
                    test_run_ids[$pos]="$run_id"
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
log "  E2E Test Results"
log "========================================="

pass=0
fail=0
timeout_count=0

for pos in "${!issue_nums[@]}"; do
    idx="${active_indices[$pos]}"
    name="${all_names[$idx]}"
    issue_num="${issue_nums[$pos]}"
    conclusion="${test_results[$pos]:-timeout}"
    run_id="${test_run_ids[$pos]}"

    if [[ "$conclusion" == "success" ]]; then
        # Check if a PR was created (OpenHands branch pattern: openhands-fix-issue-N)
        pr_count=$(gh pr list --repo "$TEST_REPO" \
            --search "head:openhands-fix-issue-$issue_num" \
            --json number --jq 'length' 2>/dev/null || echo "0")

        if [[ "$pr_count" -gt 0 ]]; then
            status="PASS"
            ((pass++)) || true
            cleanup_branches+=("openhands-fix-issue-$issue_num")
        else
            # Workflow succeeded but no PR — agent ran but didn't produce a PR.
            # This is still a "pass" for the workflow itself (config parsing,
            # agent invocation all worked). The agent just didn't solve the issue.
            status="PASS (no PR)"
            ((pass++)) || true
        fi
    elif [[ "$conclusion" == "timeout" ]]; then
        status="TIMEOUT"
        ((timeout_count++)) || true
    else
        status="FAIL ($conclusion)"
        ((fail++)) || true
        if [[ -n "$run_id" ]]; then
            log "  Logs: gh run view $run_id --repo $TEST_REPO --log | tail -40"
        fi
    fi

    printf "  %-25s %-25s issue #%s\n" "$name" "$status" "$issue_num"
done

log "========================================="
log "  Pass: $pass  Fail: $fail  Timeout: $timeout_count"
log "========================================="

# Exit with failure if any test didn't pass
if [[ $fail -gt 0 || $timeout_count -gt 0 ]]; then
    exit 1
fi
