"""
AlgoMentor — entry-point dispatcher.

Usage:
    python main.py                     # interactive CLI
    python main.py "Number of Islands" # CLI with initial problem
    python main.py telegram            # Telegram bot (long-polling)
"""
from __future__ import annotations

import sys


def _build_service():
    """Instantiate AgentService, exiting cleanly on config errors."""
    try:
        from core.agent_service import AgentService
        return AgentService()
    except RuntimeError as exc:
        print(f"\n  Configuration error: {exc}")
        print("  Add the missing key(s) to your .env file and try again.\n")
        sys.exit(1)


def main() -> None:
    args = sys.argv[1:]
    mode = args[0].lower() if args else "cli"

    if mode == "telegram":
        service = _build_service()
        from app.telegram_bot import run
        run(service)
        return

    # CLI mode — first arg (if any) is the initial problem name
    initial_problem = " ".join(args) if args else ""
    service = _build_service()
    from app.cli import run
    run(service, initial_problem=initial_problem)


if __name__ == "__main__":
    main()

