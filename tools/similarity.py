"""
Tool: similarity_scoring
Computes a lightweight structural similarity score between a target problem
and a list of candidate problems using tag overlap and keyword matching.

No embeddings or external API calls — pure Python.
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tokenise(text: str) -> set[str]:
    """Lower-case word tokens, stopwords removed."""
    stopwords = {
        "a", "an", "the", "and", "or", "of", "in", "to", "is", "are",
        "for", "with", "that", "this", "be", "on", "at", "by", "from",
        "you", "can", "given", "find", "return",
    }
    tokens = re.findall(r"[a-z]+", text.lower())
    return {t for t in tokens if t not in stopwords and len(t) > 2}


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return round(intersection / union, 4) if union else 0.0


def _tag_overlap(tags_a: list[str], tags_b: list[str]) -> float:
    sa = {t.lower() for t in tags_a}
    sb = {t.lower() for t in tags_b}
    if not sa and not sb:
        return 0.0
    return round(len(sa & sb) / max(len(sa | sb), 1), 4)


# ── LangChain tool ────────────────────────────────────────────────────────────

@tool
def similarity_scoring(
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Score structural similarity between a target problem and a list of
    candidate problems.

    Each problem dict should contain at minimum:
        - "title"       (str)
        - "tags"        (list[str])  — topic tags like BFS, DP, Graph
        - "description" (str)        — optional problem text

    Returns the candidates list enriched with a "similarity_score" (0.0–1.0)
    sorted in descending order.

    Scoring weights:
        50% — tag overlap (Jaccard on topic tags)
        50% — description keyword overlap (Jaccard on significant tokens)
    """
    target_tokens = _tokenise(target.get("description", target.get("title", "")))
    target_tags = target.get("tags", [])

    scored: list[dict[str, Any]] = []
    for cand in candidates:
        cand_tokens = _tokenise(cand.get("description", cand.get("title", "")))
        cand_tags = cand.get("tags", [])

        kw_score = _jaccard(target_tokens, cand_tokens)
        tag_score = _tag_overlap(target_tags, cand_tags)
        combined = round(0.5 * kw_score + 0.5 * tag_score, 4)

        scored.append({**cand, "similarity_score": combined})

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored
