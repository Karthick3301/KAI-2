"""
Chat history: messages, repair, truncation, Gemini sanitizing (extracted from assistant.py).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import AppConfig

@dataclass
class Message:
    role: str
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    name: Optional[str] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result

    def to_api_dict(self, provider: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.role == "assistant" and self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        if self.role == "tool":
            if provider in ("mistral", "gemini"):
                if self.name:
                    payload["name"] = self.name
                if self.tool_call_id:
                    payload["tool_call_id"] = self.tool_call_id
            else:
                payload["content"] = self.content or ""
                if provider == "ollama" and self.name:
                    payload["tool_name"] = self.name
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        content = data.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content)
        return cls(
            role=data.get("role", "user"),
            content=content,
            tool_calls=data.get("tool_calls") or [],
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
        )


def ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ollama wants tool-call arguments as JSON objects; our saved history keeps them as text
    (the OpenAI/Gemini style). Convert on a copy, so the saved history is left untouched.
    """
    converted: List[Dict[str, Any]] = []
    for message in messages:
        calls = message.get("tool_calls")
        if not calls:
            converted.append(message)
            continue
        fixed_calls = []
        for call in calls:
            function = dict(call.get("function") or {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            function["arguments"] = arguments
            fixed_calls.append({"function": function})
        converted.append({**message, "tool_calls": fixed_calls})
    return converted


def estimate_tokens(messages: List[Message]) -> int:
    total = 0
    for message in messages:
        total += max(1, len(json.dumps(message.to_dict(), ensure_ascii=False)) // 4)
    return total


def clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... (truncated for history, was {len(text)} chars)"


def _has_tool_calls(message: Message) -> bool:
    return message.role == "assistant" and bool(message.tool_calls)


def _latest_user_index(body: List[Message]) -> int:
    for index in range(len(body) - 1, -1, -1):
        if body[index].role == "user":
            return index
    return -1


def repair_history_body(body: List[Message]) -> List[Message]:
    """
    Drop orphan tool results and incomplete tool rounds so a functionCall
    always sits after a user (or earlier tool-result) turn.
    """
    repaired: List[Message] = []
    index = 0
    while index < len(body):
        message = body[index]
        if message.role == "tool":
            index += 1
            continue
        if _has_tool_calls(message):
            tools: List[Message] = []
            next_index = index + 1
            while next_index < len(body) and body[next_index].role == "tool":
                tools.append(body[next_index])
                next_index += 1
            previous_ok = bool(repaired) and repaired[-1].role in ("user", "tool")
            if previous_ok and tools:
                repaired.append(message)
                repaired.extend(tools)
            index = next_index
            continue
        repaired.append(message)
        index += 1
    return repaired


def drop_oldest_turn(body: List[Message]) -> List[Message]:
    """Remove the oldest complete user/assistant/tool group from the front."""
    if not body:
        return body
    if body[0].role == "tool":
        index = 0
        while index < len(body) and body[index].role == "tool":
            index += 1
        return body[index:]
    if _has_tool_calls(body[0]):
        index = 1
        while index < len(body) and body[index].role == "tool":
            index += 1
        return body[index:]
    if body[0].role == "assistant":
        return body[1:]
    index = 1
    while index < len(body) and body[index].role != "user":
        index += 1
    return body[index:]


def sanitize_gemini_contents(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Gemini requires each functionCall turn to follow a user turn or a
    functionResponse turn. Merge consecutive same-role model turns and
    drop anything that would violate that rule.
    """
    cleaned: List[Dict[str, Any]] = []

    def _has_part(turn: Dict[str, Any], key: str) -> bool:
        return any(key in (part or {}) for part in (turn.get("parts") or []))

    for turn in contents:
        role = turn.get("role")
        parts = list(turn.get("parts") or [])
        if not role or not parts:
            continue
        has_call = _has_part(turn, "functionCall")
        has_response = _has_part(turn, "functionResponse")

        if has_call:
            if cleaned and cleaned[-1].get("role") == "model":
                cleaned[-1]["parts"] = list(cleaned[-1].get("parts") or []) + parts
                continue
            previous = cleaned[-1] if cleaned else None
            if not (previous and previous.get("role") == "user"):
                continue

        if has_response:
            previous = cleaned[-1] if cleaned else None
            previous_has_call = bool(previous) and previous.get("role") == "model" and _has_part(previous, "functionCall")
            if not previous_has_call:
                continue

        if cleaned and cleaned[-1].get("role") == role == "model":
            cleaned[-1]["parts"] = list(cleaned[-1].get("parts") or []) + parts
            continue

        cleaned.append({"role": role, "parts": parts})

    while cleaned and cleaned[0].get("role") != "user":
        cleaned.pop(0)
    return cleaned


class ChatHistory:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.messages: List[Message] = []
        self.history_file = Path(config.chat_history_file)
        if self.history_file.exists():
            self.load()
        self.normalize()
        self.truncate()
        if self.config.auto_save and self.history_file.exists():
            self.save()

    def add_message(self, message: Message, compact: bool = True) -> None:
        self.messages.append(message)
        if compact:
            self.truncate()
            if self.config.auto_save:
                self.save()

    def compact(self) -> None:
        self.truncate()
        if self.config.auto_save:
            self.save()

    def get_api_messages(self, provider: str) -> List[Dict[str, Any]]:
        return [message.to_api_dict(provider) for message in self.messages]

    def clear(self) -> None:
        self.messages = []
        if self.history_file.exists():
            self.history_file.unlink()

    def save(self, filepath: Optional[str] = None) -> None:
        save_path = Path(filepath) if filepath else self.history_file
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as handle:
            for message in self.messages:
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")

    def load(self, filepath: Optional[str] = None) -> None:
        load_path = Path(filepath) if filepath else self.history_file
        if not load_path.exists():
            return
        loaded: List[Message] = []
        with open(load_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded.append(Message.from_dict(json.loads(line)))
                except json.JSONDecodeError:
                    continue
        self.messages = loaded

    def normalize(self) -> None:
        """Keep a single leading system prompt; drop leftover system lines from older runs."""
        system_msg: Optional[Message] = None
        rest: List[Message] = []
        seen_non_system = False
        for message in self.messages:
            if message.role == "system" and not seen_non_system:
                if system_msg is None:
                    system_msg = message
                continue
            if message.role == "system":
                continue
            seen_non_system = True
            rest.append(message)
        self.messages = ([system_msg] if system_msg else []) + rest

    def _split_system(self) -> "tuple[Optional[Message], List[Message]]":
        if self.messages and self.messages[0].role == "system":
            return self.messages[0], list(self.messages[1:])
        return None, list(self.messages)

    def _over_limit(self, system: Optional[Message], body: List[Message]) -> bool:
        combined = ([system] if system else []) + body
        return (
            len(combined) > self.config.max_history_length
            or estimate_tokens(combined) > self.config.max_history_tokens
        )

    def _shrink_tool_results(self, body: List[Message], max_chars: int) -> bool:
        changed = False
        for message in body:
            if message.role != "tool":
                continue
            clipped = clip_text(message.content or "", max_chars)
            if clipped != (message.content or ""):
                message.content = clipped
                changed = True
        return changed

    def truncate(self) -> None:
        if not self.messages:
            return
        system, body = self._split_system()
        body = repair_history_body(body)
        shrink_caps = [
            getattr(self.config, "max_tool_result_chars", 4000),
            2000,
            800,
            300,
        ]
        shrink_stage = 0

        while body and self._over_limit(system, body):
            if shrink_stage < len(shrink_caps):
                if self._shrink_tool_results(body, shrink_caps[shrink_stage]):
                    shrink_stage += 1
                    continue
                shrink_stage += 1
                continue
            latest_user = _latest_user_index(body)
            if latest_user > 0:
                body = drop_oldest_turn(body)
                body = repair_history_body(body)
                continue
            if self._shrink_tool_results(body, 200):
                continue
            break

        self.messages = ([system] if system else []) + repair_history_body(body)
