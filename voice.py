"""
Optional voice input/output. Engines are created only when voice mode is turned on.

Privacy: offline speech recognition stays on your computer, but Google
recognition sends audio to Google's cloud. VOICE_STT controls this:
  auto (default) = try offline first, then Google
  offline = local only, never sends audio out
  google = legacy behaviour, Google first then offline fallback
"""

from __future__ import annotations

import os
from typing import Optional

VOICE_IMPORT_ERROR = ""
try:
    import speech_recognition as sr
    import pyttsx3
    VOICE_SUPPORTED = True
except ImportError as exc:
    sr = None  # type: ignore
    pyttsx3 = None  # type: ignore
    VOICE_SUPPORTED = False
    VOICE_IMPORT_ERROR = str(exc)


def get_stt_mode(explicit: Optional[str] = None) -> str:
    """Which speech recognition to use. Env VOICE_STT wins unless explicit is given."""
    raw = (explicit if explicit is not None else os.getenv("VOICE_STT", "auto")).strip().lower()
    return raw if raw in ("auto", "offline", "google") else "auto"


class VoiceAssistant:
    def __init__(self) -> None:
        if not VOICE_SUPPORTED:
            raise RuntimeError(f"Voice packages are not installed: {VOICE_IMPORT_ERROR}")
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.engine = pyttsx3.init()
        voices = self.engine.getProperty("voices")
        try:
            if voices and len(voices) > 1:
                self.engine.setProperty("voice", voices[1].id)
        except Exception:
            pass
        self.engine.setProperty("rate", 150)
        self.engine.setProperty("volume", 0.9)

    def listen(self, timeout: int = 5, phrase_time_limit: int = 12, stt_mode: Optional[str] = None) -> Optional[str]:
        with self.microphone as source:
            print("\n[Listening... speak now]")
            try:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            except Exception as exc:
                print(f"[Mic error]: {exc}")
                return None

        mode = get_stt_mode(stt_mode)

        def _try_offline():
            try:
                print("Trying offline recognition (local)...")
                text = self.recognizer.recognize_sphinx(audio)
                print(f"You said: {text}")
                return text
            except Exception as exc:
                print(f"Offline recognition unavailable: {exc}")
                print("Hint: python -m pip install pocketsphinx for local STT, or set VOICE_STT=google")
                return None

        def _try_google():
            try:
                print("Trying Google recognition (sends audio to Google cloud)...")
                text = self.recognizer.recognize_google(audio)
                print(f"You said: {text}")
                return text
            except sr.UnknownValueError:
                print("Could not understand audio (Google)")
                return None
            except sr.RequestError as exc:
                print(f"Google error: {exc}")
                return None

        if mode == "offline":
            return _try_offline()
        if mode == "google":
            return _try_google() or _try_offline()
        # auto: local first to honour local-first claim
        return _try_offline() or _try_google()

    def speak(self, text: str) -> None:
        if not text:
            return
        self.engine.say(text)
        self.engine.runAndWait()

    def test(self) -> None:
        self.speak("Hello! I am your voice assistant. Say something to test.")
        result = self.listen()
        if result:
            self.speak(f"You said: {result}")
        else:
            self.speak("Sorry, I did not catch that.")


_engine: Optional[VoiceAssistant] = None


def get_engine() -> VoiceAssistant:
    global _engine
    if _engine is None:
        _engine = VoiceAssistant()
    return _engine


def contains_wake_word(text: str, wake_word: str) -> bool:
    import difflib
    haystack = " ".join((text or "").lower().split())
    needle = " ".join((wake_word or "").lower().split())
    if not needle:
        return True
    if needle in haystack:
        return True
    if haystack.startswith("kai") or haystack == "hey kai":
        return True
    # Offline STT often hears "hey kai" as "a guy" / "hey guy" / "they guard".
    # Accept close matches so the wake word works with pocketsphinx.
    if needle in ("hey kai", "hey kai".strip()):
        for variant in ("hey kai", "hey guy", "a guy", "hi kai", "hey kay", "hey kaye", "they guard", "a kai"):
            if variant in haystack:
                return True
        if difflib.SequenceMatcher(None, haystack, needle).ratio() >= 0.6:
            return True
        # last resort: heard "kai"/"guy" sound at all
        if haystack in ("a guy", "hey guy", "high guy") or " guy" in haystack or "kai" in haystack or "kay" in haystack:
            return True
        return False
    return difflib.SequenceMatcher(None, haystack, needle).ratio() >= 0.6


def get_voice_input(wake_enabled: bool = False, wake_word: str = "hey kai", stt_mode: Optional[str] = None) -> str:
    engine = get_engine()
    mode = get_stt_mode(stt_mode)
    if wake_enabled:
        print(f"Say '{wake_word}' then your request.")
        heard = engine.listen(timeout=8, phrase_time_limit=8, stt_mode=mode)
        if not heard:
            return ""
        if contains_wake_word(heard, wake_word):
            leftover = heard.lower()
            for token in (wake_word.lower(), "hey kai", "hey guy", "a guy", "hi kai", "they guard", "kai", "guy", "kay"):
                leftover = leftover.replace(token, " ", 1)
            leftover = leftover.strip(" ,.-")
            if leftover in ("a", "hey", "hi", "they"):
                leftover = ""
            if leftover:
                return leftover
            follow_up = engine.listen(timeout=8, phrase_time_limit=12, stt_mode=mode)
            return follow_up or ""
        return ""
    return engine.listen(stt_mode=mode) or ""


def speak_response(text: str) -> None:
    get_engine().speak(text)
