"""
Skill: ComplexityAnalysisSkill
Parses free-text or pseudocode and extracts / infers time + space complexity.
Pure Python — no LLM, no external calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ComplexityInfo:
    label: str           # human-readable identifier, e.g. "Approach 1"
    time: str            # e.g. "O(n log n)"
    space: str           # e.g. "O(n)"
    time_rank: int       # lower is better (1=O(1), 2=O(log n), …)
    space_rank: int


# ── Complexity rank table ─────────────────────────────────────────────────────
# Maps canonical Big-O strings to a numeric rank for comparison.

_TIME_RANK: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r"o\(1\)", re.I),             1, "O(1)"),
    (re.compile(r"o\(log\s*n\)", re.I),       2, "O(log n)"),
    (re.compile(r"o\(n\)", re.I),             3, "O(n)"),
    (re.compile(r"o\(n\s*log\s*n\)", re.I),   4, "O(n log n)"),
    (re.compile(r"o\(n\^?2\)", re.I),         5, "O(n²)"),
    (re.compile(r"o\(n\^?3\)", re.I),         6, "O(n³)"),
    (re.compile(r"o\(2\^n\)", re.I),          7, "O(2ⁿ)"),
    (re.compile(r"o\(n!\)",   re.I),          8, "O(n!)"),
]

_SPACE_RANK: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r"o\(1\)", re.I),             1, "O(1)"),
    (re.compile(r"o\(log\s*n\)", re.I),       2, "O(log n)"),
    (re.compile(r"o\(n\)", re.I),             3, "O(n)"),
    (re.compile(r"o\(n\^?2\)", re.I),         4, "O(n²)"),
]


def _extract_complexity(text: str, rank_table: list) -> tuple[str, int]:
    """Return (canonical_label, rank) for the first matching complexity in text."""
    for pattern, rank, label in rank_table:
        if pattern.search(text):
            return label, rank
    return "Unknown", 99


def _split_approaches(text: str) -> list[str]:
    """
    Split a multi-approach description into individual blocks.
    Splits on patterns like 'Approach 1', 'Method 2', '### Brute Force', etc.
    """
    splitter = re.compile(
        r"(?:^|\n)(?:#{1,4}\s*)?(?:approach|method|solution|strategy)\s*\d*[:\-.]?\s*",
        re.IGNORECASE,
    )
    parts = splitter.split(text)
    parts = [p.strip() for p in parts if p.strip()]
    return parts if parts else [text]


# ── Skill class ───────────────────────────────────────────────────────────────

class ComplexityAnalysisSkill:
    """
    Extracts time and space complexity from approach descriptions.

    Usage:
        skill = ComplexityAnalysisSkill()
        results = skill.analyse("Approach 1: BFS O(n) time O(n) space …")
    """

    def analyse(self, text: str) -> list[dict]:
        """
        Parse `text` and return a list of ComplexityInfo dicts for each
        detected approach.

        Returns:
            [
                {
                    "label": "Approach 1",
                    "time": "O(n log n)",
                    "time_rank": 4,
                    "space": "O(n)",
                    "space_rank": 3,
                },
                …
            ]
        """
        blocks = _split_approaches(text)
        results: list[dict] = []

        for i, block in enumerate(blocks):
            time_label, time_rank = _extract_complexity(block, _TIME_RANK)
            space_label, space_rank = _extract_complexity(block, _SPACE_RANK)

            # Try to extract a name for the block
            first_line = block.split("\n")[0].strip()
            label = first_line[:60] if first_line else f"Approach {i + 1}"

            results.append(
                {
                    "label": label,
                    "time": time_label,
                    "time_rank": time_rank,
                    "space": space_label,
                    "space_rank": space_rank,
                }
            )

        return results
