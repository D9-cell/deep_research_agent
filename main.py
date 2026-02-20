"""
AlgoMentor — CLI entry point

Run:
    python main.py                  # interactive loop
    python main.py "Number of Islands"   # one-shot, then interactive
"""
from __future__ import annotations

import sys

BANNER = r"""
  ___  _          __  __            _
 / _ \| | __ ___ |  \/  | ___ _ __ | |_ ___  _ __
| | | | |/ _` _ \| |\/| |/ _ \ '_ \| __/ _ \| '__|
| |_| | | (_| (_) | |  | |  __/ | | | || (_) | |
 \__,_|_|\__, \___/|_|  |_|\___|_| |_|\__\___/|_|
          |___/
  AI-Powered Algorithm Tutor  ·  Phase 1 + 2 + 3
"""

DIVIDER = "─" * 62

HELP_TEXT = """
Commands:
  <problem name>   — research a problem  (e.g. "Two Sum")
  quit / exit / q  — exit AlgoMentor
  help             — show this message
"""


def _prompt_language(default: str = "python") -> str:
    raw = input(
        f"\n  Which language? (python / java / cpp / go / typescript) [{default}]: "
    ).strip()
    return raw.lower() if raw else default


def _run_session(agent, problem_name: str) -> None:
    """Handle one complete problem session: research → gate → code."""
    print(f"\n{DIVIDER}")
    print(f"  Researching: {problem_name}")
    print(DIVIDER)

    # ── Phase 1 / 2 : explain + pseudocode ─────────────────────────────────
    research_output = agent.research_problem(problem_name)
    print(f"\n{research_output}\n")

    # ── Human approval gate ─────────────────────────────────────────────────
    print(DIVIDER)
    reply = input("  Generate code? (yes / no): ").strip().lower()
    if reply not in ("yes", "y"):
        print("  Skipping code generation.\n")
        return

    language = _prompt_language()

    # ── Code generation ─────────────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print(f"  Generating {language.capitalize()} solution…")
    print(DIVIDER)
    code_output = agent.generate_code(problem_name, language, research_output)
    print(f"\n{code_output}\n")
    print(DIVIDER)


def main() -> None:
    print(BANNER)

    # Lazy import so config errors surface cleanly
    try:
        from agent.deep_agent import build_root_agent
    except RuntimeError as exc:
        print(f"\n  ❌  Configuration error: {exc}")
        print("  Add the missing key(s) to your .env file and try again.\n")
        sys.exit(1)

    print("  Initialising AlgoMentor…")
    agent = build_root_agent()
    print("  Ready.\n")

    # If a problem name was passed as a CLI argument, handle it first
    if len(sys.argv) > 1:
        initial_problem = " ".join(sys.argv[1:])
        _run_session(agent, initial_problem)

    # Interactive loop
    print(HELP_TEXT)
    while True:
        try:
            user_input = input("  AlgoMentor > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Goodbye! Keep grinding. 💪\n")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("\n  Goodbye! Keep grinding. 💪\n")
            break
        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        try:
            _run_session(agent, user_input)
        except Exception as exc:          # noqa: BLE001
            print(f"\n  ⚠️  Unexpected error: {exc}\n")


if __name__ == "__main__":
    main()
