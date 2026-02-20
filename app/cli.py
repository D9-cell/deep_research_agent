"""
CLI transport layer.

Reads lines from stdin, forwards each to AgentService.handle_message_stream,
and prints events as they arrive:

  - Progress events  → single-line spinner / stage banner
  - Section events   → headed content block separated by dividers
  - Error events     → formatted error message

The session state machine (research → approval → language → code) is driven
entirely by AgentService; the CLI is a thin I/O adapter.
"""
from __future__ import annotations

import asyncio
import sys

from core.agent_service import AgentService
from core.events import AgentEvent, STAGE_MESSAGES
from log.logger import get_logger, log_event

_logger = get_logger(__name__)

_BANNER = r"""
  ___  _          __  __            _
 / _ \| | __ ___ |  \/  | ___ _ __ | |_ ___  _ __
| | | | |/ _` _ \| |\/| |/ _ \ '_ \| __/ _ \| '__|
| |_| | | (_| (_) | |  | |  __/ | | | || (_) | |
 \__,_|_|\__, \___/|_|  |_|\___|_| |_|\__\___/|_|
          |___/
  AI-Powered Algorithm Tutor
"""

_DIVIDER = "─" * 62
_THIN    = "·" * 62

_HELP = """
Commands:
  <problem name>   — research a problem  (e.g. "Two Sum")
  /reset           — reset your session
  quit / exit / q  — exit AlgoMentor
  help             — show this message
"""

# Stage label → display icon + label shown in the terminal
_STAGE_ICONS: dict[str, str] = {
    "fetch":     "📥  Fetching problem",
    "similar":   "🔍  Finding similar problems",
    "patterns":  "🧩  Analyzing patterns",
    "solutions": "⛏   Mining solutions",
    "strategy":  "🏆  Optimizing strategy",
    "synthesis": "🔗  Synthesizing response",
}

_USER_ID = "cli"


def _print_divider() -> None:
    print(_DIVIDER)


def _print_thin() -> None:
    print(_THIN)


def _print_stage(stage: str) -> None:
    """Print a progress stage banner."""
    label = _STAGE_ICONS.get(stage, f"◉  {stage}")
    print(f"\n  {label}…")


def _print_section(title: str, content: str) -> None:
    """Print one output section with a clear heading."""
    _print_thin()
    print(f"\n  ▌ {title.upper()}\n")
    print(content)
    print()


def run(service: AgentService, initial_problem: str = "") -> None:
    """
    Start the interactive CLI loop.

    Args:
        service:          Shared AgentService instance.
        initial_problem:  If non-empty, process this problem before the loop.
    """
    print(_BANNER)
    print(_HELP)

    log_event(_logger, "CLI transport started", user_id=_USER_ID, stage="startup")

    if initial_problem:
        _dispatch(service, initial_problem)

    while True:
        try:
            user_input = input("  AlgoMentor > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Goodbye! Keep grinding.\n")
            log_event(
                _logger, "CLI session ended by user",
                user_id=_USER_ID, stage="shutdown"
            )
            break

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ("quit", "exit", "q"):
            print("\n  Goodbye! Keep grinding.\n")
            log_event(
                _logger, "CLI session ended by user",
                user_id=_USER_ID, stage="shutdown"
            )
            break

        if lower == "help":
            print(_HELP)
            continue

        if lower == "/reset":
            service.reset_session(_USER_ID)
            print("  Session reset.\n")
            continue

        _dispatch(service, user_input)


def _dispatch(service: AgentService, text: str) -> None:
    """
    Drive one full streaming exchange with AgentService.

    Progress stages are printed immediately; sections are printed as they
    arrive so the user sees content incrementally rather than waiting for
    the entire pipeline to finish.
    """
    _print_divider()
    try:
        asyncio.run(_run_stream(service, text))
    except Exception as exc:
        _logger.error(
            "Unhandled error in CLI dispatch: %s",
            exc,
            extra={"user_id": _USER_ID, "stage": "cli"},
            exc_info=True,
        )
        print(f"\n  Error: {exc}\n")
    _print_divider()


async def _run_stream(service: AgentService, text: str) -> None:
    """Consume the event stream and render each event to stdout."""
    async for event in service.handle_message_stream(_USER_ID, text):
        _render_event(event)


def _render_event(event: AgentEvent) -> None:
    """Render a single AgentEvent to stdout."""
    if event.stage in STAGE_MESSAGES:
        _print_stage(event.stage)

    elif event.stage == "section":
        _print_section(event.section_title, event.payload)

    elif event.stage == "complete":
        pass  # nothing to render; divider follows

    elif event.stage == "error":
        _print_thin()
        print(f"\n  ⚠  {event.payload}\n")

