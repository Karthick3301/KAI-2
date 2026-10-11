import http.client
import json
import threading
import unittest
from types import SimpleNamespace

import web_server


class FakeMemory:
    def __init__(self):
        self.facts = ["likes tea"]

    def add(self, text):
        self.facts.append(text)
        return "Remembered"

    def remove(self, index):
        self.facts.pop(index - 1)
        return "Removed"

    def clear(self):
        self.facts = []
        return "Cleared"


class FakeAssistant:
    def __init__(self):
        from config import Persona
        self.persona = Persona(name="KAI", role="helper")
        self.model_config = SimpleNamespace(name="fake-model", provider="fake", ollama_base_url="http://x")
        self.tools_enabled = True
        self.memory = FakeMemory()
        self.confirm = None
        self.history = []
        self.cleared = False
        self.ask_before_reply = None
        self.last_question = None
        self.undone = False

    def get_history(self):
        return self.history

    def clear_history(self):
        self.history = []
        self.cleared = True

    def set_persona(self, persona):
        self.persona = persona

    def enable_tools(self, enabled):
        self.tools_enabled = enabled

    def undo_last_turn(self):
        self.undone = True
        return self.last_question

    def switch_chat(self, filepath):
        self.chat_file = filepath

    def refresh_system_prompt(self):
        pass

    def chat(self, message, on_token=None, on_event=None, context=None):
        self.last_context = context
        self.last_question = message
        if on_event:
            on_event("Using tool get_current_time({})")
        if self.ask_before_reply and self.confirm:
            allowed = self.confirm(self.ask_before_reply)
            reply = "allowed" if allowed else "denied"
        else:
            reply = "Echo: " + message
        for piece in (reply[:3], reply[3:]):
            if on_token:
                on_token(piece)
        return reply


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.assistant = FakeAssistant()
        self.server = web_server.make_server(self.assistant, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": host or f"127.0.0.1:{self.port}"}
        if body is not None:
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def events(self, data):
        return [json.loads(l[6:]) for l in data.decode().split("\n\n") if l.startswith("data: ")]



class WebServerTests(ServerCase):
    def test_home_page_and_state(self):
        resp, data = self.request("GET", "/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"KAI", data)
        resp, data = self.request("GET", "/api/state")
        state = json.loads(data)
        self.assertEqual(state["model"], "fake-model")
        self.assertEqual(state["memories"], ["likes tea"])

    def test_chat_streams_tokens_and_events(self):
        resp, data = self.request("POST", "/api/chat", {"message": "hi"})
        evs = self.events(data)
        self.assertEqual(resp.status, 200)
        self.assertEqual(evs[0]["type"], "event")
        self.assertEqual("".join(e["text"] for e in evs if e["type"] == "token"), "Echo: hi")
        self.assertEqual(evs[-1], {"type": "done", "reply": "Echo: hi"})

    def test_regenerate_repeats_the_last_question(self):
        self.request("POST", "/api/chat", {"message": "first question"})
        resp, data = self.request("POST", "/api/regenerate", {})
        evs = self.events(data)
        self.assertEqual(resp.status, 200)
        self.assertTrue(self.assistant.undone)
        self.assertEqual(evs[-1], {"type": "done", "reply": "Echo: first question"})

    def test_regenerate_with_nothing_to_repeat(self):
        resp, _ = self.request("POST", "/api/regenerate", {})
        self.assertEqual(resp.status, 400)
        self.assertFalse(self.server.state.busy.locked())

    def test_icon_and_manifest(self):
        resp, data = self.request("GET", "/icon.svg")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<svg", data)
        resp, data = self.request("GET", "/manifest.webmanifest")
        self.assertEqual(json.loads(data)["short_name"], "KAI")

    def test_empty_and_long_messages_rejected(self):
        self.assertEqual(self.request("POST", "/api/chat", {"message": "  "})[0].status, 400)
        big = "x" * (web_server.MAX_MESSAGE_CHARS + 1)
        self.assertEqual(self.request("POST", "/api/chat", {"message": big})[0].status, 400)

    def test_wrong_host_is_blocked(self):
        resp, _ = self.request("GET", "/api/state", host="evil.example.com")
        self.assertEqual(resp.status, 403)

    def test_other_website_origin_is_blocked(self):
        resp, _ = self.request("POST", "/api/clear", {}, headers={"Origin": "https://evil.example.com"})
        self.assertEqual(resp.status, 403)
        self.assertFalse(self.assistant.cleared)
        resp, _ = self.request("POST", "/api/clear", {}, headers={"Origin": f"http://localhost:{self.port}"})
        self.assertEqual(resp.status, 200)

    def test_post_needs_json(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/clear", "x=1", {"Content-Type": "text/plain"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()

    def test_busy_returns_409(self):
        self.server.state.busy.acquire()
        try:
            resp, _ = self.request("POST", "/api/chat", {"message": "hi"})
            self.assertEqual(resp.status, 409)
        finally:
            self.server.state.busy.release()

    def test_approval_allow_and_deny(self):
        for allow, word in ((True, "allowed"), (False, "denied")):
            self.assistant.ask_before_reply = "Allow write_file?"
            result = {}

            def run():
                result["resp"], result["data"] = self.request("POST", "/api/chat", {"message": "go"})

            t = threading.Thread(target=run)
            t.start()
            for _ in range(200):
                with self.server.state.pending_lock:
                    ids = list(self.server.state.pending)
                if ids:
                    break
                threading.Event().wait(0.02)
            self.assertTrue(ids)
            resp, data = self.request("POST", "/api/confirm", {"id": ids[0], "allow": allow})
            self.assertTrue(json.loads(data)["ok"])
            t.join(10)
            evs = self.events(result["data"])
            self.assertTrue(any(e["type"] == "confirm" for e in evs))
            self.assertEqual(evs[-1]["reply"], word)

    def test_unknown_confirm_id(self):
        _, data = self.request("POST", "/api/confirm", {"id": "nope", "allow": True})
        self.assertFalse(json.loads(data)["ok"])

    def test_memory_tools_and_clear(self):
        _, data = self.request("POST", "/api/memory", {"action": "add", "text": "likes chess"})
        self.assertIn("likes chess", json.loads(data)["memories"])
        _, data = self.request("POST", "/api/memory", {"action": "remove", "index": 1})
        self.assertEqual(json.loads(data)["memories"], ["likes chess"])
        _, data = self.request("POST", "/api/tools", {"enabled": False})
        self.assertFalse(json.loads(data)["tools"])
        resp, _ = self.request("POST", "/api/memory", {"action": "remove", "index": "x"})
        self.assertEqual(resp.status, 400)
        self.request("POST", "/api/clear", {})
        self.assertTrue(self.assistant.cleared)

    def test_persona_update_and_reset(self):
        _, data = self.request("POST", "/api/persona", {"name": "Max", "role": "a coder", "tone": "brief", "instructions": ""})
        state = json.loads(data)
        self.assertEqual((state["name"], state["role"], state["tone"]), ("Max", "a coder", "brief"))
        self.assertEqual(self.assistant.persona.name, "Max")
        _, data = self.request("POST", "/api/persona", {"reset": True})
        self.assertEqual(json.loads(data)["name"], "KAI")

    def test_persona_validation(self):
        resp, _ = self.request("POST", "/api/persona", {"name": "  "})
        self.assertEqual(resp.status, 400)
        resp, _ = self.request("POST", "/api/persona", {"name": "x" * 41})
        self.assertEqual(resp.status, 400)

    def test_models_not_switchable_for_other_providers(self):
        _, data = self.request("POST", "/api/models", {})
        self.assertFalse(json.loads(data)["can_switch"])
        resp, _ = self.request("POST", "/api/model", {"name": "x"})
        self.assertEqual(resp.status, 400)

    def test_ollama_model_switch(self):
        from unittest import mock
        self.assistant.model_config.provider = "ollama"
        with mock.patch.object(web_server, "list_ollama_models", return_value=["a:1", "b:2"]):
            _, data = self.request("POST", "/api/models", {})
            info = json.loads(data)
            self.assertTrue(info["can_switch"])
            self.assertEqual(info["models"][0], "fake-model")
            resp, _ = self.request("POST", "/api/model", {"name": "b:2"})
            self.assertEqual(resp.status, 200)
            self.assertEqual(self.assistant.model_config.name, "b:2")
            resp, _ = self.request("POST", "/api/model", {"name": "../evil"})
            self.assertEqual(resp.status, 400)


class UploadTests(ServerCase):

    def upload(self, name, raw):
        import base64
        return self.request("POST", "/api/upload", {"name": name, "data": base64.b64encode(raw).decode()})

    def test_upload_then_question_gets_excerpts(self):
        resp, data = self.upload("notes.txt", b"The warranty is 24 months for the battery.")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data)["docs"], [{"name": "notes.txt", "chars": 42}])
        self.request("POST", "/api/chat", {"message": "how long is the warranty?"})
        self.assertIn("24 months", self.assistant.last_context)

    def test_no_documents_means_no_context(self):
        self.request("POST", "/api/chat", {"message": "hi"})
        self.assertIsNone(self.assistant.last_context)

    def test_remove_document(self):
        self.upload("a.txt", b"hello there")
        _, data = self.request("POST", "/api/docs/remove", {"name": "a.txt"})
        self.assertEqual(json.loads(data)["docs"], [])

    def test_bad_uploads_are_rejected_with_a_message(self):
        resp, data = self.upload("virus.exe", b"MZ")
        self.assertEqual(resp.status, 400)
        self.assertIn("Unsupported", json.loads(data)["error"])
        resp, _ = self.request("POST", "/api/upload", {"name": "a.txt", "data": "%%%"})
        self.assertEqual(resp.status, 400)

    def test_oversized_body_is_rejected(self):
        big = "A" * (web_server.MAX_UPLOAD_BODY_BYTES + 10)
        try:
            resp, _ = self.request("POST", "/api/upload", {"name": "a.txt", "data": big})
        except (ConnectionError, OSError):
            return  # server closed the connection: also a rejection
        self.assertEqual(resp.status, 400)


class SavedChatTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from chat_store import ChatStore
        self.tmp = Path(tempfile.mkdtemp())
        self.old = self.tmp / "chat_history.jsonl"
        self.old.write_text(json.dumps({"role": "user", "content": "first question"}) + "\n", encoding="utf-8")
        self.assistant = FakeAssistant()
        self.store = ChatStore(self.tmp / "chats")
        self.server = web_server.make_server(self.assistant, "127.0.0.1", 0, store=self.store,
                                             old_history_file=str(self.old))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, json.dumps(body or {}), {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return resp.status, data

    def test_old_history_is_imported_and_opened(self):
        status, data = self.post("/api/chats")
        self.assertEqual([c["title"] for c in data["chats"]], ["first question"])
        self.assertEqual(data["active"], data["chats"][0]["id"])
        self.assertTrue(self.assistant.chat_file.endswith(data["active"] + ".jsonl"))

    def test_new_open_delete(self):
        _, first = self.post("/api/chats")
        first_id = first["active"]
        status, snap = self.post("/api/chat/new")
        self.assertEqual(status, 200)
        new_id = snap["chat_id"]
        self.assertNotEqual(new_id, first_id)
        # an empty new chat is only listed while it is open
        self.assertIn(new_id, [c["id"] for c in snap["chats"]])
        status, snap = self.post("/api/chat/open", {"id": first_id})
        self.assertEqual(snap["chat_id"], first_id)
        self.assertNotIn(new_id, [c["id"] for c in snap["chats"]])
        status, snap = self.post("/api/chat/delete", {"id": first_id})
        self.assertEqual(status, 200)
        self.assertNotEqual(snap["chat_id"], first_id)
        self.assertFalse(self.store.exists(first_id))

    def test_bad_ids_are_rejected(self):
        for bad in ("../../etc/passwd", "", "UPPER", "a" * 40, "x y"):
            self.assertEqual(self.post("/api/chat/open", {"id": bad})[0], 404)
            self.assertEqual(self.post("/api/chat/delete", {"id": bad})[0], 404)

    def test_store_titles_are_trimmed(self):
        cid = self.store.new_id()
        self.store.path(cid).write_text(json.dumps({"role": "user", "content": "w " * 100}) + "\n", encoding="utf-8")
        row = [r for r in self.store.list() if r["id"] == cid][0]
        self.assertTrue(row["title"].endswith("..."))
        self.assertLessEqual(len(row["title"]), 51)


if __name__ == "__main__":
    unittest.main()
