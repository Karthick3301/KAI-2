"""
Markdown link flattening for plain-text terminals (extracted from assistant.py).
"""

from __future__ import annotations

import re

_MD_LINK_RE = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^)\s]+)\)")


def _plain_link(match) -> str:
    text, url = match.group(1).strip(), match.group(2)
    return url if text.rstrip("/") == url.rstrip("/") or not text else f"{text}: {url}"


def flatten_markdown_links(text: str) -> str:
    """Turn [text](https://x) into 'text: https://x' so links stay plain text."""
    return _MD_LINK_RE.sub(_plain_link, text or "")


class LinkFlattener:
    """Streaming version of flatten_markdown_links: pass tokens in, plain text goes out."""

    MAX_HOLD = 400

    def __init__(self, emit):
        self.emit = emit
        self.held = ""

    def feed(self, piece: str) -> None:
        for ch in piece:
            if not self.held:
                if ch == "[":
                    self.held = ch
                else:
                    self.emit(ch)
                continue
            self.held += ch
            if "\n" in self.held or len(self.held) > self.MAX_HOLD:
                self._release()
            elif ch == "]":
                continue
            elif "](" in self.held:
                if ch == ")":
                    self._release()
            elif self.held.count("]") and not self.held.endswith("]("):
                if not self.held[self.held.index("]") + 1:].startswith("("):
                    self._release()
        # keep holding otherwise

    def _release(self) -> None:
        out = flatten_markdown_links(self.held)
        self.held = ""
        # a new "[" may be the start of another link
        if out:
            self.emit(out)

    def flush(self) -> None:
        if self.held:
            self._release()
