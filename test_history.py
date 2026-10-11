"""History repair and Gemini content sanitizing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import AppConfig
from assistant import (
    ChatHistory,
    Message,
    drop_oldest_turn,
    repair_history_body,
    sanitize_gemini_contents,
)


def _tool_call(name: str = "web_fetch") -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


class RepairTests(unittest.TestCase):
    def test_drops_leading_function_call_without_user(self) -> None:
        body = [
            Message(role="assistant", tool_calls=[_tool_call()]),
            Message(role="tool", content="<html>huge</html>", name="web_fetch", tool_call_id="call_1"),
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        repaired = repair_history_body(body)
        self.assertEqual([m.role for m in repaired], ["user", "assistant"])
        self.assertEqual(repaired[0].content, "hello")

    def test_keeps_complete_tool_round_after_user(self) -> None:
        body = [
            Message(role="user", content="find videos"),
            Message(role="assistant", tool_calls=[_tool_call()]),
            Message(role="tool", content="rss...", name="web_fetch", tool_call_id="call_1"),
        ]
        repaired = repair_history_body(body)
        self.assertEqual([m.role for m in repaired], ["user", "assistant", "tool"])

    def test_drop_oldest_turn_removes_whole_user_group(self) -> None:
        body = [
            Message(role="user", content="old"),
            Message(role="assistant", tool_calls=[_tool_call()]),
            Message(role="tool", content="x", name="web_fetch", tool_call_id="call_1"),
            Message(role="user", content="new"),
        ]
        leftover = drop_oldest_turn(body)
        self.assertEqual([m.role for m in leftover], ["user"])
        self.assertEqual(leftover[0].content, "new")


class SanitizeGeminiTests(unittest.TestCase):
    def test_drops_leading_function_call(self) -> None:
        contents = [
            {"role": "model", "parts": [{"functionCall": {"name": "web_fetch", "args": {}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "web_fetch", "response": {"content": "x"}}}]},
            {"role": "user", "parts": [{"text": "now answer"}]},
        ]
        cleaned = sanitize_gemini_contents(contents)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["parts"][0]["text"], "now answer")

    def test_merges_model_text_and_function_call(self) -> None:
        contents = [
            {"role": "user", "parts": [{"text": "search"}]},
            {"role": "model", "parts": [{"text": "one sec"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "web_fetch", "args": {}}}]},
        ]
        cleaned = sanitize_gemini_contents(contents)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[1]["role"], "model")
        self.assertEqual(len(cleaned[1]["parts"]), 2)
        self.assertIn("text", cleaned[1]["parts"][0])
        self.assertIn("functionCall", cleaned[1]["parts"][1])


class TruncateTests(unittest.TestCase):
    def test_does_not_orphan_function_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(
                chat_history_file=str(Path(tmp) / "chat.jsonl"),
                max_history_tokens=80,
                max_history_length=100,
                max_tool_result_chars=40,
                auto_save=False,
            )
            history = ChatHistory(config)
            history.add_message(Message(role="system", content="You are KAI."))
            history.add_message(Message(role="user", content="old question"))
            history.add_message(Message(role="assistant", content="old answer"))
            history.add_message(Message(role="user", content="find videos"), compact=False)
            history.add_message(
                Message(role="assistant", content="", tool_calls=[_tool_call()]),
                compact=False,
            )
            history.add_message(
                Message(
                    role="tool",
                    content="Y" * 4000,
                    name="web_fetch",
                    tool_call_id="call_1",
                ),
                compact=False,
            )
            history.compact()
            roles = [m.role for m in history.messages if m.role != "system"]
            self.assertIn("user", roles)
            if "assistant" in roles and any(m.tool_calls for m in history.messages):
                # A kept functionCall must still be preceded by a user turn.
                body = [m for m in history.messages if m.role != "system"]
                for index, message in enumerate(body):
                    if message.tool_calls:
                        self.assertGreater(index, 0)
                        self.assertEqual(body[index - 1].role, "user")


if __name__ == "__main__":
    unittest.main()
