"""Ollama needs tool-call arguments as objects, not text. A fake Ollama server enforces that."""
import json, os, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SEEN = []          # every request body the fake server receives
SCRIPT = []        # replies to give, in order (each is a list of NDJSON dicts)


class FakeOllama(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(body)
        for msg in body["messages"]:
            for call in msg.get("tool_calls") or []:
                if not isinstance(call["function"]["arguments"], dict):
                    err = json.dumps({"error": "Value looks like object, but can't find closing '}' symbol"}).encode()
                    self.send_response(400); self.send_header("Content-Length", str(len(err)))
                    self.end_headers(); self.wfile.write(err); return
        lines = SCRIPT.pop(0) if SCRIPT else [{"message": {"content": "ok"}, "done": True}]
        if body.get("stream"):
            data = ("\n".join(json.dumps(x) for x in lines) + "\n").encode()
        else:
            data = json.dumps(lines[-1]).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def log_message(self, *a): pass


srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
import assistant as A
from config import Config

REAL_REQUEST = A.request_with_retry   # other test files swap this out; we need the real one


def old_gemini_tool_round():
    """What a chat history saved during the Gemini days looks like."""
    return [
        A.Message(role="user", content="what is 6*7?"),
        A.Message(role="assistant", tool_calls=[{
            "id": "call_1", "type": "function", "gemini_thought_signature": "abc",
            "function": {"name": "calculate", "arguments": "{\"expression\": \"6*7\"}"}}]),
        A.Message(role="tool", content="42", name="calculate", tool_call_id="call_1"),
        A.Message(role="assistant", content="It is 42."),
    ]


class OllamaTests(unittest.TestCase):
    def setUp(self):
        SEEN.clear(); SCRIPT.clear()
        self._saved_env = dict(os.environ)
        self._tmp = tempfile.mkdtemp()
        os.environ.update(MODEL_PROVIDER="ollama", MODEL_NAME="llama3.2:3b", AUTO_SAVE="false",
            OLLAMA_BASE_URL=f"http://127.0.0.1:{srv.server_port}",
            WORKSPACE_DIR=f"{self._tmp}/ws", CHAT_HISTORY_FILE=f"{self._tmp}/h.jsonl",
            MEMORY_FILE=f"{self._tmp}/m.json", PERSONA_FILE=f"{self._tmp}/p.json")
        os.environ.pop("GEMINI_API_KEY", None)
        self._saved_request = A.request_with_retry
        A.request_with_retry = REAL_REQUEST
        self.bot = A.Assistant(Config())

    def tearDown(self):
        A.request_with_retry = self._saved_request
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_old_gemini_history_does_not_break_ollama(self):
        for m in old_gemini_tool_round():
            self.bot.chat_history.add_message(m, compact=False)
        reply = self.bot.chat("hi", on_token=lambda t: None)
        self.assertEqual(reply, "ok")

    def test_streaming_and_non_streaming_both_work(self):
        for m in old_gemini_tool_round():
            self.bot.chat_history.add_message(m, compact=False)
        self.bot.streaming = False
        self.assertEqual(self.bot.chat("hi"), "ok")

    def test_full_tool_round_trip_then_second_question(self):
        SCRIPT.append([{"message": {"content": "", "tool_calls": [
            {"function": {"name": "calculate", "arguments": {"expression": "6*7"}}}]}, "done": True}])
        SCRIPT.append([{"message": {"content": "The answer is 42."}, "done": True}])
        self.assertEqual(self.bot.chat("6*7?", on_token=lambda t: None), "The answer is 42.")
        # the next question re-sends the saved tool round; this used to be rejected
        self.assertEqual(self.bot.chat("and again?", on_token=lambda t: None), "ok")

    def test_tool_result_names_its_tool(self):
        for m in old_gemini_tool_round():
            self.bot.chat_history.add_message(m, compact=False)
        self.bot.chat("hi", on_token=lambda t: None)
        tool_msgs = [m for m in SEEN[-1]["messages"] if m["role"] == "tool"]
        self.assertEqual(tool_msgs[0].get("tool_name"), "calculate")

    def test_saved_history_keeps_its_original_format(self):
        for m in old_gemini_tool_round():
            self.bot.chat_history.add_message(m, compact=False)
        self.bot.chat("hi", on_token=lambda t: None)
        saved = [m for m in self.bot.chat_history.messages if m.tool_calls][0]
        self.assertIsInstance(saved.tool_calls[0]["function"]["arguments"], str)


if __name__ == "__main__":
    unittest.main()
