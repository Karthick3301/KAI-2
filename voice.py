"""
Optional voice input/output. Engines are created only when voice mode is turned on.
"""

from __future__ import annotations

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

    def listen(self, timeout: int = 5, phrase_time_limit: int = 12) -> Optional[str]:
        with self.microphone as source:
            print("\n🎤 Listening... (speak now)")
            try:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            except Exception as exc:
                print(f"❌ Microphone error: {exc}")
                return None

        try:
            print("Trying Google recognition...")
            text = self.recognizer.recognize_google(audio)
            print(f"💬 You said: {text}")
            return text
        except sr.UnknownValueError:
            print("❌ Could not understand audio (Google)")
        except sr.RequestError as exc:
            print(f"❌ Google error: {exc}")

        try:
            print("Trying offline recognition...")
            text = self.recognizer.recognize_sphinx(audio)
            print(f"💬 You said: {text}")
            return text
        except Exception as exc:
            print(f"❌ Offline recognition unavailable: {exc}")
        return None

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
    haystack = " ".join((text or "").lower().split())
    needle = " ".join((wake_word or "").lower().split())
    if not needle:
        return True
    return needle in haystack or haystack.startswith("kai") or haystack == "hey kai"


def get_voice_input(wake_enabled: bool = False, wake_word: str = "hey kai") -> str:
    engine = get_engine()
    if wake_enabled:
        print(f"Say '{wake_word}' then your request.")
        heard = engine.listen(timeout=8, phrase_time_limit=8)
        if not heard:
            return ""
        if contains_wake_word(heard, wake_word):
            leftover = heard.lower()
            for token in (wake_word.lower(), "hey kai", "kai"):
                leftover = leftover.replace(token, " ", 1)
            leftover = leftover.strip(" ,.-")
            if leftover:
                return leftover
            follow_up = engine.listen(timeout=8, phrase_time_limit=12)
            return follow_up or ""
        return ""
    return engine.listen() or ""


def speak_response(text: str) -> None:
    get_engine().speak(text)
