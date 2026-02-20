"""
Phase 3 — Memory Schema
Defines the shape of the persisted JSON memory file.

The store is a single JSON object written to memory/memory.json.
All fields have sensible defaults so a fresh install works out of the box.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# ── Per-problem record ────────────────────────────────────────────────────────

@dataclass
class ProblemRecord:
    """One entry per problem the user has worked through."""

    name: str
    slug: str                       # normalised lower-kebab form
    difficulty: str = "Unknown"
    tags: list[str] = field(default_factory=list)
    language: str = "python"
    solved_at: str = ""             # ISO-8601 timestamp
    pattern: str = "Unknown"        # primary algorithmic pattern
    session_notes: str = ""         # anything the agent captured

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "difficulty": self.difficulty,
            "tags": self.tags,
            "language": self.language,
            "solved_at": self.solved_at,
            "pattern": self.pattern,
            "session_notes": self.session_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProblemRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Aggregate user profile ────────────────────────────────────────────────────

@dataclass
class UserProfile:
    """
    Aggregated learning profile.  Persisted alongside individual problem records.
    """

    solved_count: int = 0
    preferred_language: str = "python"

    # Pattern-level performance: {pattern_name: attempt_count}
    pattern_attempts: dict[str, int] = field(default_factory=dict)
    # {pattern_name: success_count}
    pattern_successes: dict[str, int] = field(default_factory=dict)

    # Ordered list of last N topic tags seen (for "recent topics")
    recent_topics: list[str] = field(default_factory=list)

    # ISO timestamp of last session
    last_session: str = ""

    def to_dict(self) -> dict:
        return {
            "solved_count": self.solved_count,
            "preferred_language": self.preferred_language,
            "pattern_attempts": self.pattern_attempts,
            "pattern_successes": self.pattern_successes,
            "recent_topics": self.recent_topics,
            "last_session": self.last_session,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        return cls(
            solved_count=d.get("solved_count", 0),
            preferred_language=d.get("preferred_language", "python"),
            pattern_attempts=d.get("pattern_attempts", {}),
            pattern_successes=d.get("pattern_successes", {}),
            recent_topics=d.get("recent_topics", []),
            last_session=d.get("last_session", ""),
        )

    # ── Derived properties ────────────────────────────────────────────────────

    def weak_patterns(self, threshold: float = 0.5, min_attempts: int = 2) -> list[str]:
        """Patterns with success-rate < threshold and enough attempts."""
        weak: list[str] = []
        for pat, attempts in self.pattern_attempts.items():
            if attempts < min_attempts:
                continue
            successes = self.pattern_successes.get(pat, 0)
            rate = successes / attempts
            if rate < threshold:
                weak.append(pat)
        return sorted(weak)

    def strong_patterns(self, threshold: float = 0.75, min_attempts: int = 2) -> list[str]:
        """Patterns with success-rate ≥ threshold."""
        strong: list[str] = []
        for pat, attempts in self.pattern_attempts.items():
            if attempts < min_attempts:
                continue
            successes = self.pattern_successes.get(pat, 0)
            if successes / attempts >= threshold:
                strong.append(pat)
        return sorted(strong)


# ── Root memory container ─────────────────────────────────────────────────────

@dataclass
class MemorySchema:
    """Top-level container written to memory.json."""

    version: str = "1.0"
    profile: UserProfile = field(default_factory=UserProfile)
    solved_problems: list[ProblemRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "profile": self.profile.to_dict(),
            "solved_problems": [p.to_dict() for p in self.solved_problems],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemorySchema":
        return cls(
            version=d.get("version", "1.0"),
            profile=UserProfile.from_dict(d.get("profile", {})),
            solved_problems=[
                ProblemRecord.from_dict(p) for p in d.get("solved_problems", [])
            ],
        )
