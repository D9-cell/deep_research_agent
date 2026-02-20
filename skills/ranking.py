"""
Skill: StrategyRankingSkill  (ranking.py)
Ranks candidate solution approaches using a multi-criterion scoring function:
  1. Time complexity rank (lower Big-O = better)
  2. Space complexity rank (lower Big-O = better)
  3. Implementation simplicity proxy (fewer lines → simpler)
  4. Pattern popularity/interview frequency

Output is sorted best-first with numeric scores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Pattern interview frequency weights ─────────────────────────────────────
# Higher = more likely to appear in interviews → slight bonus

_PATTERN_FREQ: dict[str, float] = {
    "two pointers":       0.9,
    "sliding window":     0.9,
    "binary search":      0.85,
    "dynamic programming": 0.8,
    "dp":                 0.8,
    "bfs":                0.85,
    "dfs":                0.8,
    "greedy":             0.75,
    "heap":               0.7,
    "priority queue":     0.7,
    "trie":               0.6,
    "union find":         0.65,
    "monotonic stack":    0.65,
    "brute force":        0.2,
    "recursion":          0.5,
}

_DEFAULT_FREQ = 0.5


# ── Complexity string → numeric rank ─────────────────────────────────────────

_COMPLEXITY_RANK: list[tuple[re.Pattern, float]] = [
    (re.compile(r"o\(1\)", re.I),           1.0),
    (re.compile(r"o\(log\s*n\)", re.I),     0.9),
    (re.compile(r"o\(n\)", re.I),           0.75),
    (re.compile(r"o\(n\s*log\s*n\)", re.I), 0.6),
    (re.compile(r"o\(n\^?2\)", re.I),       0.4),
    (re.compile(r"o\(n\^?3\)", re.I),       0.2),
    (re.compile(r"o\(2\^n\)", re.I),        0.05),
    (re.compile(r"o\(n!\)", re.I),          0.01),
]


def _complexity_score(text: str) -> float:
    for pattern, score in _COMPLEXITY_RANK:
        if pattern.search(text):
            return score
    return 0.4  # middle-ground default


def _pattern_freq_score(text: str) -> float:
    lower = text.lower()
    for kw, freq in _PATTERN_FREQ.items():
        if kw in lower:
            return freq
    return _DEFAULT_FREQ


def _estimate_simplicity(text: str) -> float:
    """Proxy: fewer lines + fewer nested keywords = simpler."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    n = len(lines)
    # Penalise deeply nested logic
    nesting_kws = sum(text.lower().count(kw) for kw in ["for ", "while ", "if ", "else"])
    score = 1.0 / (1 + 0.05 * n + 0.1 * nesting_kws)
    return round(min(score, 1.0), 4)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class RankedStrategy:
    rank: int
    label: str
    time_score: float
    space_score: float
    simplicity_score: float
    frequency_score: float
    total_score: float
    justification: str


# ── Skill class ───────────────────────────────────────────────────────────────

class StrategyRankingSkill:
    """
    Ranks solution strategies by composite score.

    Weights (configurable):
        time_weight        = 0.35
        space_weight       = 0.20
        simplicity_weight  = 0.20
        frequency_weight   = 0.25

    Usage:
        skill = StrategyRankingSkill()
        ranked = skill.rank(approaches_text, complexity_analysis)
    """

    def __init__(
        self,
        time_weight: float = 0.35,
        space_weight: float = 0.20,
        simplicity_weight: float = 0.20,
        frequency_weight: float = 0.25,
    ) -> None:
        self.w_time = time_weight
        self.w_space = space_weight
        self.w_simple = simplicity_weight
        self.w_freq = frequency_weight

    def rank(
        self,
        approaches_text: str,
        complexity_analysis: list[dict] | None = None,
    ) -> list[dict]:
        """
        Rank approaches from `approaches_text`.

        Args:
            approaches_text:   Raw multi-approach string from SolutionMiningAgent.
            complexity_analysis: Optional output from ComplexityAnalysisSkill.

        Returns:
            List of ranked strategy dicts (best first), each with:
                rank, label, total_score, justification,
                time_score, space_score, simplicity_score, frequency_score
        """
        # Split into blocks
        blocks = self._split_blocks(approaches_text)
        complexity_map: dict[int, dict] = {}
        if complexity_analysis:
            for i, ca in enumerate(complexity_analysis):
                complexity_map[i] = ca

        strategies: list[RankedStrategy] = []
        for i, block in enumerate(blocks):
            ca = complexity_map.get(i, {})

            t_score = (
                _complexity_score(ca.get("time", "")) or _complexity_score(block)
            )
            s_score = (
                _complexity_score(ca.get("space", "")) or _complexity_score(block)
            )
            simp_score = _estimate_simplicity(block)
            freq_score = _pattern_freq_score(block)

            total = round(
                self.w_time * t_score
                + self.w_space * s_score
                + self.w_simple * simp_score
                + self.w_freq * freq_score,
                4,
            )

            label = block.split("\n")[0].strip()[:80] or f"Approach {i + 1}"
            justification = (
                f"time={t_score:.2f} × {self.w_time} + "
                f"space={s_score:.2f} × {self.w_space} + "
                f"simplicity={simp_score:.2f} × {self.w_simple} + "
                f"frequency={freq_score:.2f} × {self.w_freq}"
            )

            strategies.append(
                RankedStrategy(
                    rank=0,
                    label=label,
                    time_score=t_score,
                    space_score=s_score,
                    simplicity_score=simp_score,
                    frequency_score=freq_score,
                    total_score=total,
                    justification=justification,
                )
            )

        strategies.sort(key=lambda s: s.total_score, reverse=True)
        for i, s in enumerate(strategies):
            s.rank = i + 1

        return [
            {
                "rank": s.rank,
                "label": s.label,
                "total_score": s.total_score,
                "time_score": s.time_score,
                "space_score": s.space_score,
                "simplicity_score": s.simplicity_score,
                "frequency_score": s.frequency_score,
                "justification": s.justification,
            }
            for s in strategies
        ]

    @staticmethod
    def _split_blocks(text: str) -> list[str]:
        splitter = re.compile(
            r"(?:^|\n)(?:#{1,4}\s*)?(?:approach|method|solution|strategy|option)\s*\d*[:\-.]?\s*",
            re.IGNORECASE,
        )
        parts = splitter.split(text)
        return [p.strip() for p in parts if p.strip()] or [text]
