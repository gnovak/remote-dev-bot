"""Tests for trim_tool_results() and completion_with_retries() in lib/context.py."""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from lib.context import trim_tool_results, completion_with_retries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bash_call(call_id, command, is_write=False):
    """Return an assistant message with a single bash tool call."""
    if is_write:
        command = f"git commit -m 'msg'  # {command}"
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": "bash",
                    "arguments": f'{{"command": "{command}"}}',
                },
            }
        ],
    }


def _make_read_file_call(call_id, path="README.md"):
    """Return an assistant message with a single read_file tool call."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": "read_file",
                    "arguments": f'{{"path": "{path}"}}',
                },
            }
        ],
    }


def _make_grep_call(call_id, pattern="foo"):
    """Return an assistant message with a single grep tool call."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": "grep",
                    "arguments": f'{{"pattern": "{pattern}"}}',
                },
            }
        ],
    }


def _make_tool_result(call_id, content="output here"):
    """Return a tool result message."""
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _make_system():
    return {"role": "system", "content": "You are a helpful assistant."}


# ---------------------------------------------------------------------------
# Tests for trim_tool_results()
# ---------------------------------------------------------------------------


class TestTrimToolResults:

    def test_empty_messages(self):
        """Empty message list returns empty list."""
        assert trim_tool_results([], keep_n=5) == []

    def test_keep_n_zero_returns_unchanged(self):
        """keep_n=0 is the sentinel meaning 'keep everything'."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls"),
            _make_tool_result("c1", "file1"),
        ]
        result = trim_tool_results(msgs, keep_n=0)
        assert result == msgs

    def test_within_budget_unchanged(self):
        """When tool result count <= keep_n, messages are unchanged."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls"),
            _make_tool_result("c1", "file1"),
            _make_bash_call("c2", "ls -la"),
            _make_tool_result("c2", "file2"),
        ]
        result = trim_tool_results(msgs, keep_n=5)
        assert result == msgs

    def test_exactly_at_budget_unchanged(self):
        """When tool result count == keep_n, messages are unchanged."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls"),
            _make_tool_result("c1", "file1"),
            _make_bash_call("c2", "ls -la"),
            _make_tool_result("c2", "file2"),
        ]
        result = trim_tool_results(msgs, keep_n=2)
        assert result == msgs

    def test_read_only_results_trimmed_first(self):
        """Read-only bash results are dropped before write results."""
        msgs = [
            _make_system(),
            # read-only bash (oldest)
            _make_bash_call("c1", "ls -la"),
            _make_tool_result("c1", "file_listing"),
            # write bash (older but protected)
            _make_bash_call("c2", "git commit -m 'initial'"),
            _make_tool_result("c2", "commit output"),
            # read-only bash (newer, should survive if we only drop 1)
            _make_bash_call("c3", "cat README.md"),
            _make_tool_result("c3", "readme content"),
        ]
        # keep_n=2 → drop 1 (the oldest read-only: c1)
        result = trim_tool_results(msgs, keep_n=2)
        tool_results = [m for m in result if m.get("role") == "tool"]
        assert len(tool_results) == 2
        tool_ids = {m["tool_call_id"] for m in tool_results}
        assert "c1" not in tool_ids  # oldest read-only dropped
        assert "c2" in tool_ids      # write preserved
        assert "c3" in tool_ids      # newer read-only preserved

    def test_write_results_retained_over_read_results(self):
        """Write bash results outlast read-only results when trimming."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "cat file.py"),          # read-only
            _make_tool_result("c1", "content"),
            _make_bash_call("c2", "git commit -m 'fix'"),  # write
            _make_tool_result("c2", "commit ok"),
            _make_bash_call("c3", "git push"),              # write
            _make_tool_result("c3", "push ok"),
            _make_bash_call("c4", "ls"),                    # read-only
            _make_tool_result("c4", "files"),
        ]
        # keep_n=2 → drop 2; should drop c1 and c4 (the read-only ones)
        result = trim_tool_results(msgs, keep_n=2)
        tool_results = [m for m in result if m.get("role") == "tool"]
        assert len(tool_results) == 2
        tool_ids = {m["tool_call_id"] for m in tool_results}
        assert "c2" in tool_ids
        assert "c3" in tool_ids
        assert "c1" not in tool_ids
        assert "c4" not in tool_ids

    def test_read_file_and_grep_protected_from_first_drop(self):
        """read_file and grep results are kept longer than plain bash reads."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls"),            # plain bash read — dropped first
            _make_tool_result("c1", "file_list"),
            _make_read_file_call("c2"),              # read_file — protected
            _make_tool_result("c2", "file_content"),
            _make_grep_call("c3"),                   # grep — protected
            _make_tool_result("c3", "grep_results"),
        ]
        # keep_n=2 → drop 1; should drop c1 (plain bash read) not c2 or c3
        result = trim_tool_results(msgs, keep_n=2)
        tool_results = [m for m in result if m.get("role") == "tool"]
        assert len(tool_results) == 2
        tool_ids = {m["tool_call_id"] for m in tool_results}
        assert "c1" not in tool_ids
        assert "c2" in tool_ids
        assert "c3" in tool_ids

    def test_read_file_dropped_before_write_bash(self):
        """When plain bash reads are exhausted, read_file/grep are dropped next."""
        msgs = [
            _make_system(),
            _make_read_file_call("c1"),                    # protected read — dropped after bash reads
            _make_tool_result("c1", "content"),
            _make_bash_call("c2", "git commit -m 'ok'"),  # write — last to drop
            _make_tool_result("c2", "committed"),
        ]
        # keep_n=1 → drop 1; no plain bash reads left, drop read_file (c1)
        result = trim_tool_results(msgs, keep_n=1)
        tool_results = [m for m in result if m.get("role") == "tool"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_call_id"] == "c2"

    def test_assistant_text_content_preserved(self):
        """Assistant text messages (no tool_calls) are always preserved.

        When a tool call is dropped, its assistant wrapper becomes a plain
        text message containing the placeholder. The original standalone
        text messages must also survive.
        """
        msgs = [
            _make_system(),
            {"role": "assistant", "content": "I will help you."},
            _make_bash_call("c1", "ls"),
            _make_tool_result("c1", "files"),
            {"role": "assistant", "content": "I found these files."},
            _make_bash_call("c2", "cat file.py"),
            _make_tool_result("c2", "file content"),
        ]
        result = trim_tool_results(msgs, keep_n=1)
        # keep_n=1 drops c1 (oldest read-only); c2 is kept.
        # The two standalone assistant text messages survive; c1's assistant
        # message becomes a placeholder text message → 3 total assistant-text msgs.
        text_msgs = [m for m in result if m.get("role") == "assistant" and not m.get("tool_calls")]
        assert "I will help you." in [m["content"] for m in text_msgs]
        assert "I found these files." in [m["content"] for m in text_msgs]
        # Only one remaining tool result (c2)
        tool_results = [m for m in result if m.get("role") == "tool"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_call_id"] == "c2"

    def test_system_prompt_preserved(self):
        """System message is always preserved."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls"),
            _make_tool_result("c1", "files"),
        ]
        result = trim_tool_results(msgs, keep_n=0)
        # keep_n=0 means keep all
        assert result[0]["role"] == "system"

    def test_placeholder_injected_when_dropping(self):
        """When a tool call is dropped, a placeholder is injected in the assistant message."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls -la"),
            _make_tool_result("c1", "files"),
            _make_bash_call("c2", "cat file.py"),
            _make_tool_result("c2", "content"),
        ]
        result = trim_tool_results(msgs, keep_n=1)
        # The assistant message for c1 should become a plain content message
        # with a placeholder, not have tool_calls for c1
        c1_dropped = True
        for m in result:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("id") == "c1":
                        c1_dropped = False
        assert c1_dropped

    def test_no_messages_list(self):
        """Messages with no tool calls at all are returned unchanged."""
        msgs = [
            _make_system(),
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = trim_tool_results(msgs, keep_n=5)
        assert result == msgs

    def test_drop_multiple_read_only_in_order(self):
        """Multiple reads are dropped oldest-first."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "ls"),          # oldest read
            _make_tool_result("c1", "r1"),
            _make_bash_call("c2", "cat a"),       # next read
            _make_tool_result("c2", "r2"),
            _make_bash_call("c3", "cat b"),       # newest read
            _make_tool_result("c3", "r3"),
        ]
        # keep_n=2 → drop 1 oldest read (c1)
        result = trim_tool_results(msgs, keep_n=2)
        ids = {m["tool_call_id"] for m in result if m.get("role") == "tool"}
        assert "c1" not in ids
        assert "c2" in ids
        assert "c3" in ids

    def test_all_writes_when_reads_exhausted(self):
        """When all reads are gone and more drops needed, writes are dropped oldest-first."""
        msgs = [
            _make_system(),
            _make_bash_call("c1", "git commit -m 'a'"),   # oldest write
            _make_tool_result("c1", "w1"),
            _make_bash_call("c2", "git commit -m 'b'"),   # next write
            _make_tool_result("c2", "w2"),
            _make_bash_call("c3", "git push"),             # newest write
            _make_tool_result("c3", "w3"),
        ]
        # keep_n=1 → drop 2 writes (c1 and c2, oldest first)
        result = trim_tool_results(msgs, keep_n=1)
        ids = {m["tool_call_id"] for m in result if m.get("role") == "tool"}
        assert len(ids) == 1
        assert "c3" in ids


# ---------------------------------------------------------------------------
# Tests for completion_with_retries()
# ---------------------------------------------------------------------------


class TestCompletionWithRetries:

    def _make_mock_response(self, value="ok"):
        """Return a simple mock response object."""
        resp = MagicMock()
        resp.value = value
        return resp

    def test_successful_first_call_returns_immediately(self):
        """A completion_fn that succeeds immediately returns without retrying."""
        expected = self._make_mock_response("success")
        fn = MagicMock(return_value=expected)

        result = completion_with_retries(fn, "arg1", key="val")

        assert result is expected
        fn.assert_called_once_with("arg1", key="val")

    def test_passes_args_and_kwargs_to_fn(self):
        """Args and kwargs are forwarded verbatim to completion_fn."""
        fn = MagicMock(return_value="response")
        completion_with_retries(fn, "a", "b", x=1, y=2)
        fn.assert_called_once_with("a", "b", x=1, y=2)

    def test_non_retryable_exception_raised_immediately(self):
        """Non-retryable exceptions propagate without any retry."""
        fn = MagicMock(side_effect=ValueError("bad input"))

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(ValueError, match="bad input"):
                completion_with_retries(fn)
            mock_sleep.assert_not_called()

        fn.assert_called_once()

    def test_retries_on_service_unavailable(self):
        """ServiceUnavailableError triggers retry with backoff."""
        import litellm

        expected = self._make_mock_response("ok")
        service_err = litellm.exceptions.ServiceUnavailableError(
            message="overloaded", model="claude", llm_provider="anthropic"
        )
        fn = MagicMock(side_effect=[service_err, expected])

        with patch("time.sleep") as mock_sleep:
            result = completion_with_retries(fn)

        assert result is expected
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(10)  # BASE_DELAY_SECS * 2**0

    def test_retries_on_internal_server_error(self):
        """InternalServerError triggers retry with backoff."""
        import litellm

        expected = self._make_mock_response("ok")
        server_err = litellm.exceptions.InternalServerError(
            message="server error", model="claude", llm_provider="anthropic"
        )
        fn = MagicMock(side_effect=[server_err, expected])

        with patch("time.sleep") as mock_sleep:
            result = completion_with_retries(fn)

        assert result is expected
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(10)

    def test_exponential_backoff_on_multiple_failures(self):
        """Backoff doubles each attempt: 10, 20, 40, 80, 120."""
        import litellm

        expected = self._make_mock_response("final")
        make_err = lambda: litellm.exceptions.ServiceUnavailableError(
            message="busy", model="m", llm_provider="p"
        )
        fn = MagicMock(side_effect=[make_err(), make_err(), make_err(), expected])

        with patch("time.sleep") as mock_sleep:
            result = completion_with_retries(fn)

        assert result is expected
        assert fn.call_count == 4
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [10, 20, 40]  # BASE * 2^0, BASE * 2^1, BASE * 2^2

    def test_backoff_capped_at_max_delay(self):
        """Backoff is capped at MAX_DELAY_SECS=120."""
        import litellm

        # After attempt 4, delay would be 10*16=160 but capped at 120
        # Attempts: 0→10, 1→20, 2→40, 3→80, 4→120 (capped)
        expected = self._make_mock_response("ok")
        make_err = lambda: litellm.exceptions.ServiceUnavailableError(
            message="busy", model="m", llm_provider="p"
        )
        # 5 failures then success
        fn = MagicMock(side_effect=[make_err() for _ in range(5)] + [expected])

        with patch("time.sleep") as mock_sleep:
            result = completion_with_retries(fn)

        assert result is expected
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [10, 20, 40, 80, 120]

    def test_raises_after_max_retries_exhausted(self):
        """After MAX_RETRIES=5 retries, the last exception is re-raised."""
        import litellm

        make_err = lambda: litellm.exceptions.ServiceUnavailableError(
            message="always busy", model="m", llm_provider="p"
        )
        fn = MagicMock(side_effect=[make_err() for _ in range(6)])  # 6 = initial + 5 retries

        with patch("time.sleep"):
            with pytest.raises(litellm.exceptions.ServiceUnavailableError):
                completion_with_retries(fn)

        assert fn.call_count == 6  # 1 initial + 5 retries

    def test_transient_error_counter_incremented_on_retry(self):
        """transient_error_counter is incremented for each transient error."""
        import litellm

        expected = self._make_mock_response("ok")
        make_err = lambda: litellm.exceptions.ServiceUnavailableError(
            message="busy", model="m", llm_provider="p"
        )
        fn = MagicMock(side_effect=[make_err(), make_err(), expected])

        counter = [0]
        with patch("time.sleep"):
            result = completion_with_retries(fn, transient_error_counter=counter)

        assert result is expected
        assert counter[0] == 2  # two transient errors before success

    def test_transient_error_counter_incremented_on_exhaustion(self):
        """transient_error_counter is incremented even on final exhausted-retry failure."""
        import litellm

        make_err = lambda: litellm.exceptions.ServiceUnavailableError(
            message="busy", model="m", llm_provider="p"
        )
        fn = MagicMock(side_effect=[make_err() for _ in range(6)])

        counter = [0]
        with patch("time.sleep"):
            with pytest.raises(litellm.exceptions.ServiceUnavailableError):
                completion_with_retries(fn, transient_error_counter=counter)

        assert counter[0] == 6  # all 6 attempts counted

    def test_none_transient_counter_is_safe(self):
        """Passing transient_error_counter=None (default) does not crash."""
        import litellm

        expected = self._make_mock_response("ok")
        make_err = lambda: litellm.exceptions.ServiceUnavailableError(
            message="busy", model="m", llm_provider="p"
        )
        fn = MagicMock(side_effect=[make_err(), expected])

        with patch("time.sleep"):
            result = completion_with_retries(fn, transient_error_counter=None)

        assert result is expected

    def test_success_on_last_retry(self):
        """Succeeding on exactly the last retry attempt returns the response."""
        import litellm

        expected = self._make_mock_response("finally")
        make_err = lambda: litellm.exceptions.InternalServerError(
            message="error", model="m", llm_provider="p"
        )
        # 5 failures then success on attempt 6 (the 5th retry = last allowed)
        fn = MagicMock(side_effect=[make_err() for _ in range(5)] + [expected])

        with patch("time.sleep"):
            result = completion_with_retries(fn)

        assert result is expected
        assert fn.call_count == 6
