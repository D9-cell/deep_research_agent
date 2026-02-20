"""
Phase 3 — Memory Store
Reads and writes the user's learning history to a local JSON file.

The MemoryStore is the only component that touches disk.
Everything else works with in-memory Python objects.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory.schema import MemorySchema, ProblemRecord, UserProfile
from config.settings import MEMORY_FILE


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _name_to_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def _extract_pattern(research_output: str) -> str:
    """
    Try to pull the primary pattern from the agent's research output.
    Looks for lines like '🧠 PATTERN: BFS' or 'Primary pattern: DFS'.
    """
    patterns = [
        "BFS", "DFS", "Dynamic Programming", "Binary Search",
        "Sliding Window", "Two Pointers", "Graph", "Heap",
        "Trie", "Greedy", "Monotonic Stack", "Union Find",
    ]
    upper = research_output.upper()
    for pat in patterns:
        if pat.upper() in upper:
            return pat
    return "Unknown"


def _extract_tags(research_output: str) -> list[str]:
    """Extract topic tags from the 'Tags:' line in research output."""
    match = re.search(r"Tags:\s*([^\n]+)", research_output, re.IGNORECASE)
    if not match:
        return []
    return [t.strip() for t in match.group(1).split(",") if t.strip()]


# ── MemoryStore ───────────────────────────────────────────────────────────────

class MemoryStore:
    """
    Persists and retrieves user learning history.

    File location: algomentor/memory/memory.json  (auto-created on first use).

    Usage:
        store = MemoryStore()
        store.record_solved("Two Sum", language="python", research_output="…")
        snap = store.snapshot()
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or MEMORY_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: MemorySchema = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> MemorySchema:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                return MemorySchema.from_dict(raw)
            except (json.JSONDecodeError, KeyError):
                pass  # corrupted file → start fresh
        return MemorySchema()

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._data.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Write API ─────────────────────────────────────────────────────────────

    def record_solved(
        self,
        problem_name: str,
        language: str,
        research_output: str,
        difficulty: str = "Unknown",
        tags: list[str] | None = None,
    ) -> None:
        """
        Record a successfully solved problem and update the user profile.

        This is called by RootAgent.generate_code() after code is produced.
        """
        slug = _name_to_slug(problem_name)
        pattern = _extract_pattern(research_output)
        extracted_tags = tags or _extract_tags(research_output)

        record = ProblemRecord(
            name=problem_name,
            slug=slug,
            difficulty=difficulty,
            tags=extracted_tags,
            language=language,
            solved_at=_now_iso(),
            pattern=pattern,
        )

        # Avoid exact duplicate slugs (idempotent)
        existing_slugs = {p.slug for p in self._data.solved_problems}
        if slug not in existing_slugs:
            self._data.solved_problems.append(record)

        # Update profile
        profile = self._data.profile
        profile.solved_count = len(self._data.solved_problems)
        profile.preferred_language = language
        profile.last_session = _now_iso()

        # Track pattern performance
        if pattern != "Unknown":
            profile.pattern_attempts[pattern] = profile.pattern_attempts.get(pattern, 0) + 1
            profile.pattern_successes[pattern] = profile.pattern_successes.get(pattern, 0) + 1

        # Update recent topics (keep last 10)
        profile.recent_topics = (
            list(dict.fromkeys(extracted_tags + profile.recent_topics))[:10]
        )

        self._save()

    # ── Read API ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """
        Return a flat summary dict suitable for the MEMORY_CONTEXT_TEMPLATE.

        Keys:
            solved_count, preferred_language, weak_patterns, strong_patterns,
            recent_topics, solved_problems (list of slugs), last_session
        """
        profile = self._data.profile
        return {
            "solved_count": profile.solved_count,
            "preferred_language": profile.preferred_language,
            "weak_patterns": profile.weak_patterns(),
            "strong_patterns": profile.strong_patterns(),
            "recent_topics": profile.recent_topics[:5],
            "solved_problems": [p.slug for p in self._data.solved_problems],
            "last_session": profile.last_session,
        }

    def has_solved(self, problem_name: str) -> bool:
        slug = _name_to_slug(problem_name)
        return any(p.slug == slug for p in self._data.solved_problems)

    def get_record(self, problem_name: str) -> ProblemRecord | None:
        slug = _name_to_slug(problem_name)
        return next(
            (p for p in self._data.solved_problems if p.slug == slug), None
        )

    def all_records(self) -> list[ProblemRecord]:
        return list(self._data.solved_problems)
