"""Network failures must give a friendly reply and leave history consistent."""
import json, os, tempfile, unittest
import requests

tmp = tempfile.mkdtemp()
os.environ.update(MODEL_PROVIDER="gemini", GEMINI_API_KEY="fake", AUTO_SAVE="false",
    WORKSPACE_DIR=f"{tmp}/ws", CHAT_HISTORY_FILE=f"{tmp}/h.jsonl",
    MEMORY_FILE=f"{tmp}/m.json", PERSONA_FILE=f"{tmp}/p.json")
import assistant as A
from config import Config


class Dropping:
    """Streams one chunk, then the connection dies."""
    def raise_for_status(self): pass
    def iter_lines(self, decode_unicode=True):
        yield "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "Hel"}]}}]})
        raise requests.exceptions.ChunkedEncodingError("connection broken")


class Good:
    def raise_for_status(self): pass
    def iter_lines(self, decode_unicode=True):
        yield "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "All good."}]}}]})


def roles(bot):
    return [m.role for m in bot.chat_history.messages if m.role != "system"]


class NetworkErrorTests(unittest.TestCase):
    def make_bot(self):
        return A.Assistant(Config())

    def test_connection_error_before_answer(self):
        def boom(*a, **k): raise requests.exceptions.ConnectionError("no internet")
        A.request_with_retry = boom
        bot = self.make_bot()
        reply = bot.chat("hello", on_token=lambda t: None)
        self.assertIn("internet", reply.lower())
        self.assertEqual(roles(bot), ["user", "assistant"])

    def test_timeout_message(self):
        def boom(*a, **k): raise requests.exceptions.ReadTimeout("slow")
        A.request_with_retry = boom
        bot = self.make_bot()
        self.assertIn("too long", bot.chat("hello", on_token=lambda t: None))

    def test_stream_cut_off_halfway(self):
        A.request_with_retry = lambda *a, **k: Dropping()
        bot = self.make_bot()
        reply = bot.chat("hello", on_token=lambda t: None)
        self.assertIn("Something went wrong", reply)
        self.assertEqual(roles(bot), ["user", "assistant"])

    def test_recovers_on_next_message(self):
        A.request_with_retry = lambda *a, **k: Dropping()
        bot = self.make_bot()
        bot.chat("first", on_token=lambda t: None)
        A.request_with_retry = lambda *a, **k: Good()
        reply = bot.chat("second", on_token=lambda t: None)
        self.assertEqual(reply, "All good.")
        self.assertEqual(roles(bot), ["user", "assistant", "user", "assistant"])

    def test_unexpected_bug_keeps_history_consistent(self):
        def boom(*a, **k): raise KeyError("oops")
        A.request_with_retry = boom
        bot = self.make_bot()
        reply = bot.chat("hello", on_token=lambda t: None)
        self.assertIn("Unexpected error", reply)
        self.assertEqual(roles(bot), ["user", "assistant"])


if __name__ == "__main__":
    unittest.main()
