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
    def setUp(self):
        self._orig_request_with_retry = A.request_with_retry
        self._orig_env = dict(os.environ)

    def tearDown(self):
        A.request_with_retry = self._orig_request_with_retry
        os.environ.clear()
        os.environ.update(self._orig_env)

    def make_bot(self):
        return A.Assistant(Config())

    def test_retry_after_clamped(self):
        from unittest.mock import Mock, patch
        from retry import request_with_retry

        fake_resp = Mock()
        fake_resp.status_code = 429
        fake_resp.headers = {"Retry-After": "99999"}
        with patch("requests.request", return_value=fake_resp), patch("time.sleep") as mock_sleep:
            request_with_retry("POST", "https://example.com", max_retries=1, max_delay=10.0)
            self.assertTrue(mock_sleep.called)
            # Sleep delay must be clamped around max_delay + jitter, not 99999
            self.assertLess(mock_sleep.call_args[0][0], 15.0)

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
