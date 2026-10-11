"""
KAI website - a small local web server (no extra packages needed).

Run:  python web_server.py      then open  http://127.0.0.1:8000
It only listens on your own computer, so nobody else on the network can use it.
"""

from __future__ import annotations

import argparse
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

STATIC_DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BODY_BYTES = 8 * 1024 * 1024  # a 5 MB file grows to about 6.7 MB as base64
MAX_MESSAGE_CHARS = 4000
CONFIRM_TIMEOUT_SECONDS = 120
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#0b6e8a"/>'
    '<path d="M22 16v32M22 33l18-17M27 30l15 18" stroke="#fff" stroke-width="6" stroke-linecap="round" '
    'stroke-linejoin="round" fill="none"/></svg>'
)
MANIFEST = {
    "name": "KAI",
    "short_name": "KAI",
    "description": "Your personal AI assistant, running on your own computer.",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0d1418",
    "theme_color": "#0b6e8a",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
}
PERSONA_LIMITS = {"name": 40, "role": 200, "tone": 100, "instructions": 2000}


def list_ollama_models(base_url: str) -> list:
    """Names of models installed in Ollama. Empty list if Ollama is not reachable."""
    import requests

    try:
        resp = requests.get(base_url.rstrip("/") + "/api/tags", timeout=3)
        resp.raise_for_status()
        return sorted(str(m.get("name")) for m in resp.json().get("models", []) if m.get("name"))
    except Exception:
        return []


def _host_only(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.split(":")[0]


class KaiState:
    """Everything the server shares: the assistant, a 'busy' lock and pending approvals."""

    def __init__(self, assistant: Any, store: Any = None) -> None:
        self.assistant = assistant
        self.store = store  # ChatStore, or None when saved chats are off
        self.chat_id: Optional[str] = None
        self.busy = threading.Lock()
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.pending_lock = threading.Lock()

    def start_chats(self, old_history_file: Optional[str] = None) -> None:
        """Pick the chat to open at startup (newest saved one, or a fresh one)."""
        if not self.store:
            return
        if old_history_file:
            self.store.import_old_history(old_history_file)
        self.open_chat(self.store.latest_id() or self.store.new_id())

    def open_chat(self, chat_id: str) -> None:
        self.chat_id = chat_id
        self.assistant.switch_chat(str(self.store.path(chat_id)))

    def documents(self):
        """The ChatDocuments for the chat that is open right now."""
        from documents import ChatDocuments

        if self.store and self.chat_id:
            return ChatDocuments(self.store.folder / f"{self.chat_id}.docs.json")
        if not hasattr(self, "_mem_docs"):
            self._mem_docs = ChatDocuments(None)
        return self._mem_docs

    def ask_user(self, message: str, send) -> bool:
        confirm_id = uuid.uuid4().hex
        slot = {"event": threading.Event(), "allow": False}
        with self.pending_lock:
            self.pending[confirm_id] = slot
        try:
            send({"type": "confirm", "id": confirm_id, "message": message})
            slot["event"].wait(CONFIRM_TIMEOUT_SECONDS)
            return bool(slot["allow"]) if slot["event"].is_set() else False
        finally:
            with self.pending_lock:
                self.pending.pop(confirm_id, None)

    def answer(self, confirm_id: str, allow: bool) -> bool:
        with self.pending_lock:
            slot = self.pending.get(confirm_id)
        if not slot:
            return False
        slot["allow"] = allow
        slot["event"].set()
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "KAIWeb/1.0"

    @property
    def state(self) -> KaiState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # keep the terminal quiet
        pass

    # ---------- safety checks ----------
    def _allowed(self) -> bool:
        if _host_only(self.headers.get("Host", "")) not in LOCAL_HOSTS:
            return False  # blocks DNS-rebinding tricks
        origin = self.headers.get("Origin")
        if origin:
            host = origin.split("://", 1)[-1].split("/")[0]
            if _host_only(host) not in LOCAL_HOSTS:
                return False  # blocks other websites calling KAI
        return True

    def _reject(self) -> None:
        self._json({"error": "Forbidden"}, 403)

    # ---------- helpers ----------
    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, limit: int = MAX_BODY_BYTES) -> Optional[Dict[str, Any]]:
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > limit:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _snapshot(self) -> Dict[str, Any]:
        a = self.state.assistant
        history = []
        for msg in a.get_history():
            if msg.role in ("user", "assistant") and msg.content and not msg.tool_calls:
                history.append({"role": msg.role, "content": msg.content})
        return {
            "name": a.persona.name,
            "role": a.persona.role,
            "tone": getattr(a.persona, "tone", ""),
            "instructions": getattr(a.persona, "instructions", ""),
            "model": a.model_config.name,
            "provider": a.model_config.provider,
            "chat_id": self.state.chat_id,
            "docs": self.state.documents().summary(self.state.documents().load()),
            "tools": bool(a.tools_enabled),
            "memories": list(a.memory.facts),
            "history": history,
        }

    # ---------- GET ----------
    def do_GET(self) -> None:
        if not self._allowed():
            return self._reject()
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            page = STATIC_DIR / "index.html"
            if not page.exists():
                return self._json({"error": "index.html is missing (keep it in the same folder as web_server.py)"}, 500)
            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/icon.svg":
            body = ICON_SVG.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/manifest.webmanifest":
            body = json.dumps(MANIFEST).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            return self._json(self._snapshot())
        self._json({"error": "Not found"}, 404)

    # ---------- POST ----------
    def do_POST(self) -> None:
        if not self._allowed():
            return self._reject()
        path = self.path.split("?", 1)[0]
        data = self._read_json(MAX_UPLOAD_BODY_BYTES if path == "/api/upload" else MAX_BODY_BYTES)
        if data is None:
            return self._json({"error": "Send JSON (Content-Type: application/json), and keep it small."}, 400)
        a = self.state.assistant

        if path == "/api/chat":
            return self._chat(data)
        if path == "/api/regenerate":
            return self._chat({}, regenerate=True)
        if path == "/api/confirm":
            ok = self.state.answer(str(data.get("id", "")), bool(data.get("allow")))
            return self._json({"ok": ok})
        if path == "/api/clear":
            if not self.state.busy.acquire(blocking=False):
                return self._json({"error": "KAI is busy"}, 409)
            try:
                a.clear_history()
            finally:
                self.state.busy.release()
            return self._json(self._snapshot())
        if path == "/api/tools":
            a.enable_tools(bool(data.get("enabled")))
            return self._json(self._snapshot())
        if path in ("/api/upload", "/api/docs/remove"):
            return self._docs(path, data)
        if path.startswith("/api/chats") or path.startswith("/api/chat/"):
            return self._chats(path, data)
        if path == "/api/persona":
            return self._persona(data)
        if path == "/api/models":
            return self._json(self._models())
        if path == "/api/model":
            return self._set_model(data)
        if path == "/api/memory":
            action = data.get("action")
            if action == "add":
                result = a.memory.add(str(data.get("text", ""))[:500])
            elif action == "remove":
                try:
                    result = a.memory.remove(int(data.get("index")))
                except (TypeError, ValueError):
                    return self._json({"error": "index must be a number"}, 400)
            elif action == "clear":
                result = a.memory.clear()
            else:
                return self._json({"error": "Unknown action"}, 400)
            a.refresh_system_prompt()
            snap = self._snapshot()
            snap["message"] = result
            return self._json(snap)
        self._json({"error": "Not found"}, 404)

    def _docs(self, path: str, data: Dict[str, Any]) -> None:
        from documents import ChatDocuments, DocumentError, decode_upload, extract_text, safe_name

        if not self.state.busy.acquire(blocking=False):
            return self._json({"error": "KAI is busy"}, 409)
        try:
            docs = self.state.documents()
            if path == "/api/upload":
                name = safe_name(data.get("name", ""))
                text = extract_text(name, decode_upload(str(data.get("data", ""))))
                docs.add(name, text)
            else:
                docs.remove(safe_name(data.get("name", "")))
        except DocumentError as exc:
            return self._json({"error": str(exc)}, 400)
        finally:
            self.state.busy.release()
        return self._json(self._snapshot())

    def _chats(self, path: str, data: Dict[str, Any]) -> None:
        state = self.state
        store = state.store
        if store is None:
            return self._json({"error": "Saved chats are not enabled"}, 404)
        if path == "/api/chats":
            return self._json({"chats": store.list(keep=state.chat_id), "active": state.chat_id})
        if not state.busy.acquire(blocking=False):
            return self._json({"error": "KAI is busy"}, 409)
        try:
            if path == "/api/chat/new":
                state.open_chat(store.new_id())
            elif path == "/api/chat/open":
                chat_id = str(data.get("id", ""))
                if not store.exists(chat_id):
                    return self._json({"error": "Chat not found"}, 404)
                state.open_chat(chat_id)
            elif path == "/api/chat/delete":
                chat_id = str(data.get("id", ""))
                if not store.valid_id(chat_id) or not store.delete(chat_id):
                    return self._json({"error": "Chat not found"}, 404)
                if chat_id == state.chat_id:
                    state.open_chat(store.latest_id() or store.new_id())
            else:
                return self._json({"error": "Not found"}, 404)
        finally:
            state.busy.release()
        snap = self._snapshot()
        snap["chats"] = store.list(keep=state.chat_id)
        return self._json(snap)

    def _persona(self, data: Dict[str, Any]) -> None:
        from config import Persona

        a = self.state.assistant
        values = {}
        for key, limit in PERSONA_LIMITS.items():
            value = str(data.get(key, "")).strip()
            if len(value) > limit:
                return self._json({"error": f"{key} is too long (max {limit} characters)"}, 400)
            values[key] = value
        if data.get("reset"):
            fresh = Persona()
            values = {"name": fresh.name, "role": fresh.role, "tone": fresh.tone, "instructions": ""}
        if not values["name"]:
            return self._json({"error": "Name cannot be empty"}, 400)
        if not self.state.busy.acquire(blocking=False):
            return self._json({"error": "KAI is busy"}, 409)
        try:
            current = a.persona
            a.set_persona(Persona(
                name=values["name"],
                role=values["role"] or current.role,
                tone=values["tone"] or current.tone,
                instructions=values["instructions"],
                capabilities=current.capabilities,
                limitations=current.limitations,
            ))
        finally:
            self.state.busy.release()
        return self._json(self._snapshot())

    def _models(self) -> Dict[str, Any]:
        mc = self.state.assistant.model_config
        if mc.provider != "ollama":
            return {"provider": mc.provider, "current": mc.name, "models": [], "can_switch": False}
        names = list_ollama_models(mc.ollama_base_url)
        if mc.name not in names:
            names.insert(0, mc.name)
        return {"provider": mc.provider, "current": mc.name, "models": names, "can_switch": True}

    def _set_model(self, data: Dict[str, Any]) -> None:
        a = self.state.assistant
        if a.model_config.provider != "ollama":
            return self._json({"error": "Only Ollama models can be switched here. Change MODEL_NAME in .env."}, 400)
        name = str(data.get("name", "")).strip()
        if name not in list_ollama_models(a.model_config.ollama_base_url):
            return self._json({"error": "That model is not installed in Ollama."}, 400)
        if not self.state.busy.acquire(blocking=False):
            return self._json({"error": "KAI is busy"}, 409)
        try:
            a.model_config.name = name
        finally:
            self.state.busy.release()
        return self._json(self._snapshot())

    def _chat(self, data: Dict[str, Any], regenerate: bool = False) -> None:
        message = str(data.get("message", "")).strip()
        if not regenerate:
            if not message:
                return self._json({"error": "Message is empty"}, 400)
            if len(message) > MAX_MESSAGE_CHARS:
                return self._json({"error": f"Message is too long (max {MAX_MESSAGE_CHARS} characters)"}, 400)
        if not self.state.busy.acquire(blocking=False):
            return self._json({"error": "KAI is still answering. Wait a moment."}, 409)
        if regenerate:
            # take back the last answer and ask the same question again
            message = (self.state.assistant.undo_last_turn() or "").strip()
            if not message:
                self.state.busy.release()
                return self._json({"error": "There is nothing to try again."}, 400)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        alive = True
        write_lock = threading.Lock()

        def send(payload: Dict[str, Any]) -> None:
            nonlocal alive
            if not alive:
                return
            line = ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
            with write_lock:
                try:
                    self.wfile.write(line)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    alive = False

        assistant = self.state.assistant
        from documents import build_context

        context = build_context(self.state.documents().load(), message)
        previous_confirm = assistant.confirm
        assistant.confirm = lambda text: self.state.ask_user(text, send) if alive else False
        try:
            extra = {"context": context} if context else {}
            reply = assistant.chat(
                message,
                on_token=lambda piece: send({"type": "token", "text": piece}),
                on_event=lambda text: send({"type": "event", "text": text}),
                **extra,
            )
            send({"type": "done", "reply": reply})
        except Exception as exc:  # the assistant handles most errors itself
            send({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            assistant.confirm = previous_confirm
            self.state.busy.release()


def make_server(assistant: Any, host: str = "127.0.0.1", port: int = 8000, store: Any = None,
                old_history_file: Optional[str] = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.state = KaiState(assistant, store)  # type: ignore[attr-defined]
    server.state.start_chats(old_history_file)  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="KAI website (local)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-tools", action="store_true")
    args = parser.parse_args()

    from assistant import Assistant
    from config import get_config

    config = get_config()
    if args.no_tools:
        config.app_config.tools_enabled = False
    config.app_config.plain_text = False  # the web page shows bold, lists and links properly
    assistant = Assistant(config)
    from chat_store import ChatStore

    history_file = Path(assistant.app_config.chat_history_file)
    store = ChatStore(history_file.parent / "chats")
    server = make_server(assistant, "127.0.0.1", args.port, store=store, old_history_file=str(history_file))
    print(f"KAI website is running: http://127.0.0.1:{args.port}")
    print(f"Model: {assistant.model_config.name} ({assistant.model_config.provider}). Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
