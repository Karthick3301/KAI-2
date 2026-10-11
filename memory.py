"""
Long-term memory separate from session chat history.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import List


def _same_fact_key(text: str) -> str:
    """Lowercase, collapse spaces, drop trailing punctuation so near-identical facts match."""
    return re.sub(r"\s+", " ", text.strip().casefold()).rstrip(" .!?,;")


class LongTermMemory:
    def __init__(self, filepath: str) -> None:
        self.path = Path(filepath)
        self.facts: List[str] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.facts = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.facts = [str(item).strip() for item in data if str(item).strip()]
            elif isinstance(data, dict):
                self.facts = [str(item).strip() for item in data.get("facts", []) if str(item).strip()]
            else:
                self.facts = []
        except (OSError, json.JSONDecodeError):
            self.facts = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.facts, indent=2), encoding="utf-8")

    def add(self, fact: str) -> str:
        cleaned = fact.strip()
        if not cleaned:
            return "Nothing to remember."
        key = _same_fact_key(cleaned)
        if any(_same_fact_key(existing) == key for existing in self.facts):
            return f"Already remembered: {cleaned}"
        self.facts.append(cleaned)
        self.save()
        return f"Remembered: {cleaned}"

    def remove(self, index: int) -> str:
        if index < 1 or index > len(self.facts):
            return f"No memory at index {index}."
        removed = self.facts.pop(index - 1)
        self.save()
        return f"Forgot: {removed}"

    def clear(self) -> str:
        self.facts = []
        self.save()
        return "Long-term memory cleared."

    def as_prompt_block(self) -> str:
        if not self.facts:
            return ""
        lines = "\n".join(f"- {fact}" for fact in self.facts)
        return (
            "Long-term memory about the user (keep using these facts unless they contradict "
            f"the current message):\n{lines}"
        )
