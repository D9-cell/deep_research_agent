"""
Skill: PatternClassifierSkill
Deterministically maps problem text / tags to known algorithmic patterns
using keyword matching.  No LLM call — pure Python heuristics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Pattern definitions ───────────────────────────────────────────────────────

@dataclass
class _Pattern:
    name: str
    keywords: list[str]
    data_structures: list[str] = field(default_factory=list)
    weight: float = 1.0   # relative importance for tie-breaking


_PATTERNS: list[_Pattern] = [
    _Pattern(
        name="BFS",
        keywords=[
            "shortest path", "minimum steps", "level order", "nearest",
            "closest", "flood fill", "rotting", "jump game", "word ladder",
            "01 matrix", "walls and gates",
        ],
        data_structures=["Queue", "Deque"],
    ),
    _Pattern(
        name="DFS",
        keywords=[
            "all paths", "number of islands", "connected components",
            "cycle detection", "topological sort", "backtracking",
            "permutations", "combinations", "subsets", "n-queens",
            "word search", "pacific atlantic", "clone graph",
        ],
        data_structures=["Stack", "Recursion", "Visited set"],
        weight=1.1,
    ),
    _Pattern(
        name="Dynamic Programming",
        keywords=[
            "dp", "dynamic programming", "optimal substructure",
            "overlapping subproblems", "minimum cost", "maximum profit",
            "ways to", "count ways", "longest common subsequence",
            "longest increasing subsequence", "knapsack", "coin change",
            "edit distance", "house robber", "climbing stairs",
            "unique paths", "partition equal subset",
        ],
        data_structures=["1D DP array", "2D DP table", "Memoisation dict"],
        weight=1.2,
    ),
    _Pattern(
        name="Binary Search",
        keywords=[
            "binary search", "sorted array", "search in rotated",
            "find minimum in rotated", "first bad version", "peak element",
            "search matrix", "median of two sorted", "kth smallest",
        ],
        data_structures=["Array", "Sorted list"],
    ),
    _Pattern(
        name="Sliding Window",
        keywords=[
            "sliding window", "subarray", "maximum sum subarray",
            "longest substring without repeating", "minimum window substring",
            "at most k distinct", "contiguous",
        ],
        data_structures=["HashMap", "Deque", "Two pointers"],
    ),
    _Pattern(
        name="Two Pointers",
        keywords=[
            "two pointers", "three sum", "container with most water",
            "trapping rain water", "palindrome", "valid palindrome",
            "remove duplicates", "move zeroes",
        ],
        data_structures=["Array"],
    ),
    _Pattern(
        name="Graph",
        keywords=[
            "graph", "nodes", "edges", "adjacency", "directed", "undirected",
            "weighted", "bipartite", "union find", "disjoint set",
            "minimum spanning tree", "prims", "kruskal", "dijkstra",
            "bellman ford", "detect cycle",
        ],
        data_structures=["Adjacency list", "Union-Find", "Priority Queue"],
        weight=0.9,
    ),
    _Pattern(
        name="Heap / Priority Queue",
        keywords=[
            "kth largest", "kth smallest", "top k", "k closest",
            "median from data stream", "merge k sorted", "task scheduler",
            "reorganize string",
        ],
        data_structures=["Min-Heap", "Max-Heap"],
    ),
    _Pattern(
        name="Trie",
        keywords=[
            "trie", "prefix", "word dictionary", "autocomplete",
            "replace words", "implement trie",
        ],
        data_structures=["Trie node"],
    ),
    _Pattern(
        name="Monotonic Stack",
        keywords=[
            "next greater element", "next smaller element", "daily temperatures",
            "largest rectangle", "sum of subarray minimums", "asteroid collision",
        ],
        data_structures=["Stack"],
    ),
    _Pattern(
        name="Greedy",
        keywords=[
            "greedy", "interval scheduling", "meeting rooms", "minimum number of",
            "gas station", "jump game ii", "assign cookies",
        ],
        data_structures=["Sorted array"],
    ),
]


# ── Classifier ────────────────────────────────────────────────────────────────

class PatternClassifierSkill:
    """
    Fast, deterministic pattern classifier.

    Usage:
        skill = PatternClassifierSkill()
        result = skill.classify("Find shortest path in grid problem")
    """

    def classify(self, text: str) -> dict:
        """
        Classify algorithmic patterns present in `text`.

        Returns:
            {
                "primary_pattern": str,
                "secondary_patterns": list[str],
                "data_structures": list[str],
                "confidence": float,
                "scores": {pattern_name: score, ...}
            }
        """
        normalised = text.lower()
        scores: dict[str, float] = {}

        for pattern in _PATTERNS:
            hits = sum(
                1 for kw in pattern.keywords
                if re.search(r"\b" + re.escape(kw) + r"\b", normalised)
            )
            if hits:
                scores[pattern.name] = round(hits * pattern.weight, 3)

        if not scores:
            return {
                "primary_pattern": "Unknown",
                "secondary_patterns": [],
                "data_structures": [],
                "confidence": 0.0,
                "scores": {},
            }

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary_name = ranked[0][0]
        primary_pattern = next(p for p in _PATTERNS if p.name == primary_name)

        secondary = [name for name, _ in ranked[1:4]]  # top 3 secondary
        all_ds: list[str] = list(primary_pattern.data_structures)
        for name, _ in ranked[1:3]:
            pat = next((p for p in _PATTERNS if p.name == name), None)
            if pat:
                all_ds.extend(pat.data_structures)

        # Confidence: ratio of top score to max conceivable (~10 keyword hits)
        max_score = ranked[0][1]
        confidence = min(round(max_score / 8.0, 2), 1.0)

        return {
            "primary_pattern": primary_name,
            "secondary_patterns": secondary,
            "data_structures": list(dict.fromkeys(all_ds)),  # preserve order, dedupe
            "confidence": confidence,
            "scores": {k: v for k, v in ranked},
        }
