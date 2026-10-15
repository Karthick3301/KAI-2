"""
Personal AI Assistant - Configuration
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{key} in your .env file must be a whole number, but it is {value!r}.") from None


def env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{key} in your .env file must be a number, but it is {value!r}.") from None


def env_path(key: str, default: str) -> str:
    value = os.getenv(key, default).strip() or default
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


@dataclass
class ModelConfig:
    name: str = "mistral-small-latest"
    provider: str = "mistral"
    temperature: float = 0.7
    max_tokens: int = 2048
    num_ctx: int = 8192  # how much text a local Ollama model can see at once
    ollama_base_url: str = "http://localhost:11434"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_base_url_native: str = "https://generativelanguage.googleapis.com/v1beta"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.name,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


# Older saved persona.json files carry this wording; it is upgraded when loaded.
OLD_DEFAULT_CAPABILITIES = [
    "answer questions",
    "use tools for time, files, math, and web pages",
    "remember facts the user asks you to keep",
]


@dataclass
class Persona:
    name: str = "KAI"
    role: str = "a helpful personal AI assistant"
    tone: str = "friendly and professional"
    instructions: str = ""
    capabilities: List[str] = field(default_factory=lambda: [
        "answer questions",
        "use tools for time, files, math, web search, and web pages",
        "remember facts the user asks you to keep",
    ])
    limitations: List[str] = field(default_factory=lambda: [
        "file tools only work inside the workspace folder",
        "web_fetch can read a page but cannot browse interactively",
    ])

    def build_system_prompt(self) -> str:
        if self.instructions.strip():
            base = self.instructions.strip()
        else:
            base = f"You are {self.name}, {self.role}. Respond in a {self.tone} tone."
            if self.capabilities:
                base += f" You can: {', '.join(self.capabilities)}."
            if self.limitations:
                base += f" Limits: {'; '.join(self.limitations)}."
        return base

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "tone": self.tone,
            "instructions": self.instructions,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Persona":
        defaults = cls()
        saved_capabilities = data.get("capabilities")
        if saved_capabilities == OLD_DEFAULT_CAPABILITIES:
            saved_capabilities = None
        return cls(
            name=data.get("name") or defaults.name,
            role=data.get("role") or defaults.role,
            tone=data.get("tone") or defaults.tone,
            instructions=data.get("instructions") or "",
            capabilities=saved_capabilities or defaults.capabilities,
            limitations=data.get("limitations") or defaults.limitations,
        )


@dataclass
class AppConfig:
    chat_history_file: str = "chat_history.jsonl"
    memory_file: str = "memory.json"
    persona_file: str = "persona.json"
    workspace_dir: str = "workspace"
    max_history_length: int = 100
    max_history_tokens: int = 12000
    debug_mode: bool = False
    auto_save: bool = True
    tools_enabled: bool = True
    streaming: bool = True
    voice_available_default_off: bool = True
    voice_wake_enabled: bool = False
    voice_wake_word: str = "hey kai"
    web_fetch_max_chars: int = 8000
    max_tool_result_chars: int = 4000
    max_tool_iterations: int = 8
    plain_text: bool = True


class Config:
    def __init__(self) -> None:
        self.mistral_api_key: Optional[str] = os.getenv("MISTRAL_API_KEY") or None
        self.gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY") or None
        provider = os.getenv("MODEL_PROVIDER", "mistral").strip().lower()
        if provider not in ("mistral", "ollama", "gemini"):
            raise ValueError("MODEL_PROVIDER must be 'mistral', 'ollama', or 'gemini'")

        default_model_names = {
            "mistral": "mistral-small-latest",
            "ollama": "qwen2.5:7b",
            "gemini": "gemini-3.6-flash",
        }
        self.model_config = ModelConfig(
            name=(os.getenv("MODEL_NAME") or "").strip() or default_model_names[provider],
            provider=provider,
            temperature=env_float("TEMPERATURE", 0.7),
            max_tokens=env_int("MAX_TOKENS", 2048),
            num_ctx=env_int("OLLAMA_NUM_CTX", 8192),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
            ).rstrip("/"),
            gemini_base_url_native=os.getenv(
                "GEMINI_BASE_URL_NATIVE", "https://generativelanguage.googleapis.com/v1beta"
            ).rstrip("/"),
        )
        self.app_config = AppConfig(
            chat_history_file=env_path("CHAT_HISTORY_FILE", "chat_history.jsonl"),
            memory_file=env_path("MEMORY_FILE", "memory.json"),
            persona_file=env_path("PERSONA_FILE", "persona.json"),
            workspace_dir=env_path("WORKSPACE_DIR", "workspace"),
            max_history_length=env_int("MAX_HISTORY_LENGTH", 100),
            max_history_tokens=env_int("MAX_HISTORY_TOKENS", 12000),
            debug_mode=env_bool("DEBUG_MODE", False),
            auto_save=env_bool("AUTO_SAVE", True),
            tools_enabled=env_bool("TOOLS_ENABLED", True),
            streaming=env_bool("STREAMING", True),
            voice_wake_enabled=env_bool("VOICE_WAKE_ENABLED", False),
            voice_wake_word=os.getenv("VOICE_WAKE_WORD", "hey kai"),
            web_fetch_max_chars=env_int("WEB_FETCH_MAX_CHARS", 8000),
            max_tool_result_chars=env_int("MAX_TOOL_RESULT_CHARS", 4000),
            max_tool_iterations=env_int("MAX_TOOL_ITERATIONS", 8),
            plain_text=env_bool("PLAIN_TEXT", True),
        )
        self.persona = self._load_persona()
        Path(self.app_config.workspace_dir).mkdir(parents=True, exist_ok=True)

        if provider == "mistral" and not self.mistral_api_key:
            raise ValueError("Put your Mistral API key in .env as MISTRAL_API_KEY")
        if provider == "gemini" and not self.gemini_api_key:
            raise ValueError("Put your Gemini API key in .env as GEMINI_API_KEY")

    def _load_persona(self) -> Persona:
        persona = Persona(
            name=os.getenv("ASSISTANT_NAME", "KAI"),
            role=os.getenv("ASSISTANT_ROLE", "a helpful personal AI assistant"),
            tone=os.getenv("ASSISTANT_TONE", "friendly and professional"),
            instructions=os.getenv("ASSISTANT_INSTRUCTIONS", ""),
        )
        persona_path = Path(self.app_config.persona_file)
        if persona_path.exists():
            try:
                data = json.loads(persona_path.read_text(encoding="utf-8"))
                persona = Persona.from_dict(data)
            except (OSError, json.JSONDecodeError):
                pass
        return persona

    def save_persona(self, persona: Optional[Persona] = None) -> None:
        current = persona or self.persona
        path = Path(self.app_config.persona_file)
        path.write_text(json.dumps(current.to_dict(), indent=2), encoding="utf-8")

    def get_system_prompt(self) -> str:
        return self.persona.build_system_prompt()


def get_config() -> Config:
    return Config()
