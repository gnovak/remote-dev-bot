"""Tests for context window compaction (lib/context.py)."""

import pytest
from lib.context import estimate_tokens, compact_messages, _extract_text


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_string_content(self):
        messages = [{"role": "user", "content": "a" * 400}]
        assert estimate_tokens(messages) == 100  # 400 / 4

    def test_none_content(self):
        messages = [{"role": "assistant", "content": None}]
        assert estimate_tokens(messages) == 0

    def test_list_content(self):
        messages = [{"role": "user", "content": [{"text": "a" * 200}]}]
        assert estimate_tokens(messages) == 50

    def test_list_with_string_blocks(self):
        messages = [{"role": "user", "content": ["hello", "world"]}]
        assert estimate_tokens(messages) == (5 + 5) // 4  # 10 / 4 = 2

    def test_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "bash", "arguments": "a" * 100}}
                ],
            }
        ]
        assert estimate_tokens(messages) == (4 + 100) // 4  # "bash" + args

    def test_multiple_messages(self):
        messages = [
            {"role": "system", "content": "a" * 40},
            {"role": "user", "content": "b" * 80},
        ]
        assert estimate_tokens(messages) == (40 + 80) // 4  # 30


class TestExtractText:
    def test_string(self):
        assert _extract_text({"content": "hello"}) == "hello"

    def test_none(self):
        assert _extract_text({"content": None}) == ""

    def test_list(self):
        assert _extract_text({"content": [{"text": "a"}, {"text": "b"}]}) == "a\nb"

    def test_no_content(self):
        assert _extract_text({}) == ""


class TestCompactMessages:
    def _make_messages(self, n):
        """Create a conversation with system prompt + n messages."""
        msgs = [{"role": "system", "content": "You are a helpful assistant."}]
        for i in range(n):
            if i % 2 == 0:
                msgs.append({"role": "user", "content": f"User message {i}: " + "x" * 200})
            else:
                msgs.append({"role": "assistant", "content": f"Assistant message {i}: " + "y" * 200})
        return msgs

    def _mock_llm(self, summary_text="Summary of conversation."):
        """Return a mock LLM call function."""
        def call(messages, max_tokens):
            return summary_text
        return call

    def test_too_few_messages(self):
        """With < 3 messages, no compaction happens."""
        msgs = [{"role": "system", "content": "Hi"}, {"role": "user", "content": "Hello"}]
        new_msgs, stats = compact_messages(msgs, 0.5, 0.5, self._mock_llm())
        assert len(new_msgs) == 2
        assert stats["messages_compacted"] == 0

    def test_basic_compaction(self):
        """Basic compaction replaces oldest messages with summary."""
        msgs = self._make_messages(10)  # system + 10 = 11 total
        summary_text = "Compacted summary of old messages."
        new_msgs, stats = compact_messages(msgs, 0.5, 0.5, self._mock_llm(summary_text))
        
        # Should have compacted 5 of 10 post-system messages
        assert stats["messages_compacted"] == 5
        # New messages: system + summary + 5 remaining = 7
        assert len(new_msgs) == 7
        # First message is system
        assert new_msgs[0]["role"] == "system"
        # Second message is the compacted summary
        assert "[COMPACTED HISTORY" in new_msgs[1]["content"]
        assert summary_text in new_msgs[1]["content"]
        assert new_msgs[1]["role"] == "user"

    def test_preserves_recent_messages(self):
        """Compaction always preserves at least 2 recent messages."""
        msgs = self._make_messages(3)  # system + 3
        new_msgs, stats = compact_messages(msgs, 1.0, 0.5, self._mock_llm("Summary"))
        # With coverage=1.0, it would want all 3, but must keep at least 2 recent
        # So only 1 is compacted
        assert stats["messages_compacted"] == 1
        assert len(new_msgs) == 4  # system + summary + 2 remaining

    def test_compaction_coverage(self):
        """Different coverage fractions compact different amounts."""
        msgs = self._make_messages(20)  # system + 20
        # coverage=0.25 -> compact 5 of 20
        new_msgs, stats = compact_messages(msgs, 0.25, 0.5, self._mock_llm("Summary"))
        assert stats["messages_compacted"] == 5
        assert len(new_msgs) == 17  # system + summary + 15 remaining

    def test_llm_failure_returns_unchanged(self):
        """If LLM call fails, return messages unchanged."""
        msgs = self._make_messages(10)

        def failing_llm(messages, max_tokens):
            raise Exception("API error")

        new_msgs, stats = compact_messages(msgs, 0.5, 0.5, failing_llm)
        assert len(new_msgs) == len(msgs)
        assert stats["messages_compacted"] == 0

    def test_empty_summary_returns_unchanged(self):
        """If LLM returns empty summary, return messages unchanged."""
        msgs = self._make_messages(10)
        new_msgs, stats = compact_messages(msgs, 0.5, 0.5, self._mock_llm(""))
        assert len(new_msgs) == len(msgs)
        assert stats["messages_compacted"] == 0

    def test_tokens_before_after(self):
        """Stats include token estimates."""
        msgs = self._make_messages(10)
        summary = "Short summary."
        new_msgs, stats = compact_messages(msgs, 0.5, 0.5, self._mock_llm(summary))
        assert stats["tokens_before"] > 0
        assert stats["tokens_after"] > 0
        assert stats["tokens_after"] < stats["tokens_before"]

    def test_handles_tool_calls_in_messages(self):
        """Messages with tool_calls are handled without error."""
        msgs = [
            {"role": "system", "content": "System prompt."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls"}'}}
            ]},
            {"role": "tool", "content": "file1.py\nfile2.py"},
            {"role": "user", "content": "Good, now edit file1.py"},
            {"role": "assistant", "content": "I'll edit file1.py now."},
        ]
        new_msgs, stats = compact_messages(msgs, 0.5, 0.5, self._mock_llm("Summary"))
        assert stats["messages_compacted"] == 2
        assert len(new_msgs) == 4  # system + summary + 2 remaining
