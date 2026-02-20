"""
Tool: memory_store_tool  (Phase 3)
Exposes the MemoryStore to the Root Agent as a callable LangChain tool.

The agent can:
  - query  → get a summary snapshot of the user's learning history
  - lookup → check if a specific problem was solved before
"""
from __future__ import annotations

from langchain_core.tools import tool

from memory.store import MemoryStore

# Lazily initialised singleton — avoids re-opening the file on every call
_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


@tool
def memory_store_tool(action: str, problem_name: str = "") -> dict:
    """
    Query the user's persistent learning memory.

    Actions:
        "snapshot"  — return a full summary of solved problems, weak/strong
                      patterns, preferred language, and recent topics.
        "lookup"    — check if `problem_name` has been solved before and
                      return the stored record if it exists.

    Args:
        action:       "snapshot" or "lookup"
        problem_name: (required for "lookup") the problem to look up.

    Returns:
        A dict describing the memory state for the requested action.
    """
    store = _get_store()

    if action == "snapshot":
        return store.snapshot()

    if action == "lookup":
        if not problem_name:
            return {"error": "problem_name is required for action='lookup'"}
        record = store.get_record(problem_name)
        if record is None:
            return {"found": False, "problem_name": problem_name}
        return {
            "found": True,
            "name": record.name,
            "difficulty": record.difficulty,
            "tags": record.tags,
            "language": record.language,
            "pattern": record.pattern,
            "solved_at": record.solved_at,
        }

    return {"error": f"Unknown action '{action}'. Use 'snapshot' or 'lookup'."}
