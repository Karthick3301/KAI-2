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
    def _first_user_text_and_count(self, path: Path) -> tuple[str, int]:
        first, count = "", 0
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("role") == "user":
                        count += 1
                        if not first:
                            first = " ".join(str(msg.get("content") or "").split())
        except OSError:
            pass
        return first, count

    def list(self, keep: Optional[str] = None) -> List[Dict[str, Any]]:
        """Chats with at least one user message (plus `keep`, the open one), newest first."""
        rows = []
        for path in self.folder.glob("*.jsonl"):
            chat_id = path.stem
            if not self.valid_id(chat_id):
                continue
            first, count = self._first_user_text_and_count(path)
            if count == 0 and chat_id != keep:
                continue
            title = first[:TITLE_CHARS].rstrip() + ("..." if len(first) > TITLE_CHARS else "")
            rows.append({
                "id": chat_id,
                "title": title or "New chat",
                "messages": count,
                "updated": path.stat().st_mtime,
            })
        if keep and self.valid_id(keep) and all(r["id"] != keep for r in rows):
            rows.append({"id": keep, "title": "New chat", "messages": 0, "updated": time.time()})
        rows.sort(key=lambda r: r["updated"], reverse=True)
        return rows

    # ---- changing ----
    def delete(self, chat_id: str) -> bool:
        path = self.path(chat_id)
        if not path.exists():
            return False
        path.unlink()
        docs = self.folder / f"{chat_id}.docs.json"
        if docs.exists():
            docs.unlink()
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
