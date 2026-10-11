"""
Personal AI Assistant - CLI
"""

from __future__ import annotations

import argparse
import sys

from config import Persona, get_config
from assistant import Assistant
from voice import VOICE_IMPORT_ERROR, VOICE_SUPPORTED, get_engine, get_voice_input, speak_response

VOICE_AVAILABLE = VOICE_SUPPORTED
VOICE_MODE = False


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


def print_color(text: str, color: str = "", bold: bool = False, end: str = "\n") -> None:
    color_code = getattr(Colors, color.upper(), Colors.RESET) if color else ""
    prefixes = []
    if bold:
        prefixes.append(Colors.BOLD)
    if color_code:
        prefixes.append(color_code)
    print("".join(prefixes) + text + Colors.RESET, end=end)


def print_header() -> None:
    print_color("KAI — Personal AI Assistant", "CYAN", bold=True)
    print_color("=" * 50, "CYAN")
    hint = "Type /help for commands"
    if VOICE_AVAILABLE:
        hint += " | /voice on to speak"
    print_color(hint, "DIM")
    print()


def typed_input(prompt: str = "") -> str:
    try:
        if prompt:
            print_color(prompt, end="")
        return input()
    except (EOFError, KeyboardInterrupt):
        return "/exit"


def get_user_input(
    prompt: str = "",
    allow_voice: bool = True,
    wake_enabled: bool = False,
    wake_word: str = "hey kai",
) -> str:
    try:
        if prompt:
            print_color(prompt, end="")
        if allow_voice and VOICE_MODE:
            spoken = get_voice_input(wake_enabled, wake_word)
            if spoken:
                print()
                return spoken
            print_color("(no speech heard, type instead)", "DIM")
            print()
        return input()
    except (EOFError, KeyboardInterrupt):
        return "/exit"


def confirm_action(message: str) -> bool:
    print_color(f"\n{message}", "YELLOW")
    answer = typed_input("Allow? (y/n): ").strip().lower()
    return answer in ("y", "yes")


def stream_response(assistant: Assistant, user_message: str) -> None:
    pieces: list[str] = []
    prefix_open = False

    def open_prefix() -> None:
        nonlocal prefix_open
        if not prefix_open:
            print_color(f"\n{assistant.persona.name}: ", "GREEN", end="")
            prefix_open = True

    def on_token(token: str) -> None:
        open_prefix()
        pieces.append(token)
        print(token, end="", flush=True)

    def on_event(event: str) -> None:
        nonlocal prefix_open
        print_color(f"\n{event}", "DIM")
        prefix_open = False

    response = assistant.chat(user_message, on_token=on_token, on_event=on_event)
    if not pieces:
        open_prefix()
        print(response, end="")
    print("\n")
    if VOICE_MODE:
        speak_response(response)


def show_help() -> None:
    print_color("\nAvailable commands:", "YELLOW", bold=True)
    print("  /help              Show this help message")
    print("  /clear             Clear session chat history (keeps long-term memory)")
    print("  /save [path]       Save chat history")
    print("  /tools             Toggle tool calling")
    print("  /persona           View or change persona (saved to persona.json)")
    print("  /memory list       Show long-term memories")
    print("  /memory add TEXT   Save a lasting fact")
    print("  /memory remove N   Delete memory by number")
    print("  /memory clear      Clear long-term memory")
    print("  /history           Show recent chat")
    print("  /info              Show configuration")
    print("  /exit              Quit")
    if VOICE_AVAILABLE:
        print("\nVoice:")
        print("  /voice on          Listen each turn and speak replies")
        print("  /voice off         Keyboard only (default)")
        print("  /voice wake on     Require wake word before a spoken request")
        print("  /voice wake off    Speak the full request directly")
        print("  /voice test        Microphone and speaker check")
    else:
        print_color(f"\nVoice packages not installed: {VOICE_IMPORT_ERROR}", "DIM")


def handle_command(command: str, assistant: Assistant, args: argparse.Namespace) -> bool:
    global VOICE_MODE
    parts = command.strip().split(maxsplit=2)
    head = parts[0].lower() if parts else ""
    rest = command[len(parts[0]):].strip() if parts else ""

    if head in ("help", "?"):
        show_help()
        return True

    if head in ("clear", "reset"):
        assistant.clear_history()
        print_color("\nChat history cleared. Long-term memory is unchanged.", "GREEN")
        return True

    if head in ("exit", "quit", "q"):
        print_color("\nGoodbye!", "CYAN")
        return False

    if head == "save":
        filepath = rest or args.history_file or assistant.app_config.chat_history_file
        assistant.save_history(filepath)
        print_color(f"\nChat history saved to {filepath}", "GREEN")
        return True

    if head in ("tools", "tool"):
        assistant.enable_tools(not assistant.tools_enabled)
        status = "enabled" if assistant.tools_enabled else "disabled"
        print_color(f"\nTools are now {status}", "GREEN")
        return True

    if head == "voice":
        action = rest.lower()
        if not VOICE_AVAILABLE:
            print_color("\nVoice is unavailable. Install SpeechRecognition and pyttsx3.", "RED")
            return True
        if action in ("on", "enable"):
            get_engine()
            VOICE_MODE = True
            print_color("\nVoice mode on. Speak after the prompt, or type instead if nothing is heard.", "GREEN")
            return True
        if action in ("off", "disable"):
            VOICE_MODE = False
            print_color("\nVoice mode off.", "GREEN")
            return True
        if action == "test":
            print_color("\nTesting voice...", "YELLOW")
            get_engine().test()
            return True
        if action in ("wake on", "wake"):
            assistant.app_config.voice_wake_enabled = True
            print_color(f"\nWake word on: say '{assistant.app_config.voice_wake_word}' first.", "GREEN")
            return True
        if action == "wake off":
            assistant.app_config.voice_wake_enabled = False
            print_color("\nWake word off.", "GREEN")
            return True
        print_color("\nUsage: /voice on | off | test | wake on | wake off", "YELLOW")
        return True

    if head in ("persona", "character"):
        print_color("\nCurrent persona:", "YELLOW", bold=True)
        print(f"  Name: {assistant.persona.name}")
        print(f"  Role: {assistant.persona.role}")
        print(f"  Tone: {assistant.persona.tone}")
        print(f"  Instructions: {assistant.persona.instructions or 'None'}")
        print("\nEnter new values (blank keeps current). Typing only — voice is ignored here.")
        name = typed_input("  Name: ")
        if name.startswith("/"):
            return True
        role = typed_input("  Role: ")
        tone = typed_input("  Tone: ")
        instructions = typed_input("  Instructions: ")
        new_persona = Persona(
            name=name.strip() or assistant.persona.name,
            role=role.strip() or assistant.persona.role,
            tone=tone.strip() or assistant.persona.tone,
            instructions=instructions.strip() or assistant.persona.instructions,
            capabilities=assistant.persona.capabilities,
            limitations=assistant.persona.limitations,
        )
        assistant.set_persona(new_persona)
        print_color("\nPersona updated and saved to persona.json. Chat history was kept.", "GREEN")
        return True

    if head == "memory":
        sub_parts = rest.split(maxsplit=1)
        action = (sub_parts[0] if sub_parts else "list").lower()
        payload = sub_parts[1] if len(sub_parts) > 1 else ""
        if action == "list" or action == "":
            facts = assistant.memory.facts
            if not facts:
                print_color("\nNo long-term memories yet.", "YELLOW")
            else:
                print_color("\nLong-term memory:", "YELLOW", bold=True)
                for index, fact in enumerate(facts, start=1):
                    print(f"  {index}. {fact}")
            return True
        if action == "add":
            if not payload:
                payload = typed_input("Fact to remember: ").strip()
            print_color(f"\n{assistant.memory.add(payload)}", "GREEN")
            assistant.refresh_system_prompt()
            return True
        if action in ("remove", "delete", "forget"):
            try:
                index = int(payload)
            except ValueError:
                print_color("\nUsage: /memory remove 1", "YELLOW")
                return True
            print_color(f"\n{assistant.memory.remove(index)}", "GREEN")
            assistant.refresh_system_prompt()
            return True
        if action == "clear":
            print_color(f"\n{assistant.memory.clear()}", "GREEN")
            assistant.refresh_system_prompt()
            return True
        print_color("\nUsage: /memory list | add TEXT | remove N | clear", "YELLOW")
        return True

    if head in ("info", "config", "status"):
        print_color("\nCurrent configuration:", "YELLOW", bold=True)
        print(f"  Model: {assistant.model_config.name}")
        print(f"  Provider: {assistant.model_config.provider}")
        print(f"  Temperature: {assistant.model_config.temperature}")
        print(f"  Max tokens: {assistant.model_config.max_tokens}")
        print(f"  Tools: {'enabled' if assistant.tools_enabled else 'disabled'}")
        print(f"  Streaming: {'enabled' if assistant.streaming else 'disabled'}")
        print(f"  Voice available: {VOICE_AVAILABLE}")
        print(f"  Voice mode: {'on' if VOICE_MODE else 'off'}")
        print(f"  Wake word: {'on' if assistant.app_config.voice_wake_enabled else 'off'} ({assistant.app_config.voice_wake_word})")
        print(f"  Persona: {assistant.persona.name}")
        print(f"  Workspace: {assistant.app_config.workspace_dir}")
        print(f"  Memories: {len(assistant.memory.facts)}")
        return True

    if head in ("history", "log"):
        print_color("\nChat history:", "YELLOW", bold=True)
        for index, msg in enumerate(assistant.get_history(), start=1):
            role_color = "GREEN" if msg.role == "assistant" else "WHITE"
            preview = (msg.content or "")[:120]
            extra = " [tool_calls]" if msg.tool_calls else ""
            print_color(f"  {index}. [{msg.role}]{extra}", role_color)
            print(f"      {preview}")
        return True

    print_color(f"\nUnknown command: {command}. Try /help.", "RED")
    return True


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--no-tools", action="store_true", default=False)
    parser.add_argument("--clear", action="store_true", default=False, help="Clear session history on start")
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--voice", action="store_true", default=False, help="Start with voice mode on")
    parser.add_argument("--no-stream", action="store_true", default=False)
    parser.add_argument("--history-file", default=None)
    parser.add_argument("--help", "-h", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    global VOICE_MODE
    args = parse_arguments()

    if args.help:
        print_header()
        print("Usage: python main.py [--no-tools] [--clear] [--debug] [--voice] [--no-stream]")
        show_help()
        return

    try:
        config = get_config()
        if args.no_tools:
            config.app_config.tools_enabled = False
        if args.debug:
            config.app_config.debug_mode = True
        if args.no_stream:
            config.app_config.streaming = False
        if args.history_file:
            config.app_config.chat_history_file = args.history_file

        assistant = Assistant(config)
        assistant.confirm = confirm_action
        if args.clear:
            assistant.clear_history()

        if args.voice:
            if not VOICE_AVAILABLE:
                print_color("Voice flag ignored; speech packages are not installed.", "YELLOW")
            else:
                get_engine()
                VOICE_MODE = True

        print_header()
        print_color(f"Model: {assistant.model_config.name}", "WHITE")
        print_color(f"Provider: {assistant.model_config.provider}", "WHITE")
        print_color(f"Persona: {assistant.persona.name}", "WHITE")
        print_color(f"Tools: {'on' if assistant.tools_enabled else 'off'}", "WHITE")
        print_color(f"Voice mode: {'on' if VOICE_MODE else 'off'}", "WHITE")
        print_color(f"Workspace: {assistant.app_config.workspace_dir}", "WHITE")

        while True:
            try:
                print_color(f"\n{Colors.GREEN}You:{Colors.RESET} ", end="")
                user_input = get_user_input(
                    wake_enabled=assistant.app_config.voice_wake_enabled,
                    wake_word=assistant.app_config.voice_wake_word,
                )
                if not user_input.strip():
                    continue
                if user_input.startswith("/"):
                    command = user_input[1:].strip()
                    if not handle_command(command, assistant, args):
                        break
                    continue

                stream_response(assistant, user_message=user_input)
            except Exception as exc:
                print_color(f"\nError: {exc}", "RED")
                if args.debug or assistant.app_config.debug_mode:
                    import traceback
                    traceback.print_exc()
                continue

        print_color("\nGoodbye!", "CYAN")
    except Exception as exc:
        print_color(f"\nFatal error: {exc}", "RED")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
