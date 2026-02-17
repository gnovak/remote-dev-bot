#!/bin/bash
# Test command extraction logic from resolve.yml
# This tests the bash script that normalizes spaces to dashes

set -e

test_count=0
pass_count=0

function test_extraction() {
  local description="$1"
  local input="$2"
  local expected="$3"

  test_count=$((test_count + 1))

  # Simulate the extraction logic from resolve.yml
  COMMENT="$input"

  # Try dash format first: /agent-resolve-claude-large
  COMMAND=$(echo "$COMMENT" | grep -oP '^/agent-\K[a-z0-9-]+' || echo "")

  # If no match, try space format: /agent resolve claude large
  if [ -z "$COMMAND" ]; then
    COMMAND=$(echo "$COMMENT" | grep -oP '^/agent\s+\K[a-z0-9\s-]+' | head -1 | sed 's/\s\+/-/g' || echo "")
  fi

  if [ "$COMMAND" = "$expected" ]; then
    echo "✓ Test $test_count passed: $description"
    pass_count=$((pass_count + 1))
  else
    echo "✗ Test $test_count FAILED: $description"
    echo "  Input: '$input'"
    echo "  Expected: '$expected'"
    echo "  Got: '$COMMAND'"
  fi
}

# Test dash format (existing behavior)
test_extraction "Dash format: resolve" "/agent-resolve" "resolve"
test_extraction "Dash format: resolve with model" "/agent-resolve-claude-large" "resolve-claude-large"
test_extraction "Dash format: design" "/agent-design" "design"
test_extraction "Dash format: design with model" "/agent-design-claude-small" "design-claude-small"

# Test space format (new behavior)
test_extraction "Space format: resolve" "/agent resolve" "resolve"
test_extraction "Space format: resolve with model" "/agent resolve claude large" "resolve-claude-large"
test_extraction "Space format: design" "/agent design" "design"
test_extraction "Space format: design with model" "/agent design claude small" "design-claude-small"

# Test edge cases
test_extraction "Bare /agent returns empty" "/agent" ""
test_extraction "Command with trailing text (dash)" "/agent-resolve some extra text" "resolve"
test_extraction "Command with trailing text (space)" "/agent resolve claude large
Some additional comments" "resolve-claude-large"

# Test mixed dashes in model name
test_extraction "Model with multiple dashes (dash format)" "/agent-resolve-openai-large" "resolve-openai-large"
test_extraction "Model with multiple dashes (space format)" "/agent resolve openai large" "resolve-openai-large"

echo ""
echo "Results: $pass_count/$test_count tests passed"

if [ $pass_count -eq $test_count ]; then
  echo "All tests passed!"
  exit 0
else
  echo "Some tests failed!"
  exit 1
fi
