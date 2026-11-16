"""
Several saved chats for the website: one small file per chat inside a `chats/` folder.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ID_PATTERN = re.compile(r"^[a-z0-9]{8,32}$")
TITLE_CHARS = 48


class ChatStore:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    # ---- ids and paths ----
    @staticmethod
    def valid_id(chat_id: str) -> bool:
        return bool(ID_PATTERN.match(chat_id or ""))

    def new_id(self) -> str:
        return f"{int(time.time()):x}{secrets.token_hex(3)}"

    def path(self, chat_id: str) -> Path:
        if not self.valid_id(chat_id):
            raise ValueError("Invalid chat id")
        return self.folder / f"{chat_id}.jsonl"

    def exists(self, chat_id: str) -> bool:
        return self.valid_id(chat_id) and self.path(chat_id).exists()

    # ---- reading ----
    def _chat_meta(self, path: Path, chat_id: str) -> tuple[str, int, float]:
        first, count = "", 0
        last_time = 0.0
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = msg.get("timestamp")
                    if isinstance(ts, (int, float)) and ts > 0:
                        last_time = max(last_time, float(ts))
                    if msg.get("role") == "user":
                        count += 1
                        if not first:
                            first = " ".join(str(msg.get("content") or "").split())
        except OSError:
            pass

        if last_time > 0:
            updated = last_time
        else:
            try:
                # Chat IDs start with the 8-character hex unix creation timestamp
                updated = float(int(chat_id[:8], 16)) if len(chat_id) >= 8 else path.stat().st_mtime
            except (ValueError, OSError):
                try:
                    updated = path.stat().st_mtime
                except OSError:
                    updated = time.time()

        return first, count, updated

    def _first_user_text_and_count(self, path: Path) -> tuple[str, int]:
        first, count, _ = self._chat_meta(path, path.stem)
        return first, count

    def meta_path(self, chat_id: str) -> Path:
        if not self.valid_id(chat_id):
            raise ValueError("Invalid chat id")
        return self.folder / f"{chat_id}.meta.json"

    def get_meta(self, chat_id: str) -> Dict[str, Any]:
        try:
            path = self.meta_path(chat_id)
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError):
            return {}

    def set_meta(self, chat_id: str, data: Dict[str, Any]) -> None:
        path = self.meta_path(chat_id)
        existing = self.get_meta(chat_id)
        existing.update(data)
        path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    def list(self, keep: Optional[str] = None) -> List[Dict[str, Any]]:
        """Chats with at least one user message (plus `keep`, the open one), newest first."""
        rows = []
        for path in self.folder.glob("*.jsonl"):
            chat_id = path.stem
            if not self.valid_id(chat_id):
                continue
            first, count, updated = self._chat_meta(path, chat_id)
            if count == 0 and chat_id != keep:
                continue
            meta = self.get_meta(chat_id)
            custom_title = str(meta.get("title", "")).strip()
            pinned = bool(meta.get("pinned", False))
            display_title = custom_title or (first[:TITLE_CHARS].rstrip() + ("..." if len(first) > TITLE_CHARS else ""))
            rows.append({
                "id": chat_id,
                "title": display_title or "New chat",
                "custom_title": custom_title,
                "pinned": pinned,
                "messages": count,
                "updated": time.time() if count == 0 else updated,
            })
        if keep and self.valid_id(keep) and all(r["id"] != keep for r in rows):
            rows.append({"id": keep, "title": "New chat", "custom_title": "", "pinned": False, "messages": 0, "updated": time.time()})
        rows.sort(key=lambda r: (1 if r.get("pinned") else 0, r["updated"]), reverse=True)
        return rows

    def prune_empty(self, keep: Optional[str] = None) -> None:
        """Remove leftover chat files that have zero user messages and are not currently open."""
        for path in self.folder.glob("*.jsonl"):
            chat_id = path.stem
            if not self.valid_id(chat_id) or chat_id == keep:
                continue
            _, count = self._first_user_text_and_count(path)
            if count == 0:
                self.delete(chat_id)

    # ---- changing ----
    def delete(self, chat_id: str) -> bool:
        path = self.path(chat_id)
        if not path.exists():
            return False
        path.unlink()
        docs = self.folder / f"{chat_id}.docs.json"
        if docs.exists():
            docs.unlink()
        meta = self.folder / f"{chat_id}.meta.json"
        if meta.exists():
            meta.unlink()
        return True

    def import_old_history(self, old_file: str | Path) -> Optional[str]:
        """First run: bring the terminal chat history in as a chat, so nothing is lost."""
        old = Path(old_file)
        if not old.exists() or any(self.folder.glob("*.jsonl")):
            return None
        chat_id = self.new_id()
        shutil.copyfile(old, self.path(chat_id))
        return chat_id

    def latest_id(self) -> Optional[str]:
        rows = self.list()
        return rows[0]["id"] if rows else None
