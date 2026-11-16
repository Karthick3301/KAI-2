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


class PlainTextFilter:
    """Streaming filter for terminal output: keeps replies plain.

    Removes markdown bold markers (**text** / __text__), backticks (inline code and
    fences) and heading marks at the start of a line. A lone * or _ is left alone so
    sums like "2 * 3" and names like "snake_case" stay readable.
    """

    MARKERS = "*_`#"

    def __init__(self, emit):
        self.emit = emit
        self.held = ""
        self.line_start = True
        self.skip_space = False
        self.prev_char = ""

    def feed(self, piece: str) -> None:
        for ch in piece:
            if self.held:
                if ch == self.held[0]:
                    self.held += ch
                    continue
                self._release(next_ch=ch)
            if self.skip_space and ch == " ":
                self.skip_space = False
                continue
            self.skip_space = False
            if ch in self.MARKERS:
                self.held = ch
            else:
                self._out(ch)

    def _out(self, text: str) -> None:
        self.emit(text)
        if text:
            self.prev_char = text[-1]
        self.line_start = text.endswith("\n")

    def _release(self, next_ch: str = "") -> None:
        held, self.held = self.held, ""
        marker = held[0]
        if marker == "`":
            return  # code markers only add noise in a terminal
        if marker == "#":
            if self.line_start:
                self.skip_space = True
                return
            self._out(held)
            return
        if len(held) == 1:
            self._out(held)  # lone * or _: likely maths or a name, keep it
            return
        # A double asterisk like '2 ** 10' or '2**10' is math exponentiation, not markdown bold
        if held == "**" and (
            (self.prev_char in (" ", "\t") and next_ch in (" ", "\t"))
            or (self.prev_char.isdigit() and next_ch.isdigit())
        ):
            self._out(held)

    def flush(self) -> None:
        if self.held:
            self._release()


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
