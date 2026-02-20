"""
Tool: leetcode_scraper
Fetches problem statement, constraints, examples, hints, and topic tags
from LeetCode's public GraphQL API — no authentication required.
Falls back gracefully when the problem cannot be found.
"""
import re

import requests
from langchain_core.tools import tool

from config.settings import LEETCODE_GRAPHQL_URL

# ── GraphQL query ─────────────────────────────────────────────────────────────
_PROBLEM_QUERY = """
query getProblem($titleSlug: String!) {
    question(titleSlug: $titleSlug) {
        title
        titleSlug
        difficulty
        content
        topicTags { name }
        hints
        exampleTestcases
        sampleTestCase
        stats
    }
}
"""

_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _name_to_slug(name: str) -> str:
    """Convert 'Number of Islands' → 'number-of-islands'."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)   # strip punctuation
    slug = re.sub(r"\s+", "-", slug)             # spaces → hyphens
    slug = re.sub(r"-{2,}", "-", slug)           # collapse multiple hyphens
    return slug.strip("-")


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


def _fetch_problem(slug: str) -> dict | None:
    """Hit LeetCode GraphQL and return the raw question dict or None on failure."""
    payload = {"query": _PROBLEM_QUERY, "variables": {"titleSlug": slug}}
    try:
        resp = requests.post(
            LEETCODE_GRAPHQL_URL,
            json=payload,
            headers=_HEADERS,
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("question")
    except Exception:
        return None


# ── Exported tool ─────────────────────────────────────────────────────────────

@tool
def leetcode_scraper(problem_name: str) -> dict:
    """
    Retrieve a LeetCode problem's full statement, difficulty, topic tags,
    hints, and sample test cases by problem name.

    The name is automatically converted to a URL slug, so both
    'Number of Islands' and 'number-of-islands' work.

    Returns a dict with keys:
        found (bool), title, difficulty, tags, description, hints,
        sample_input, error (if not found).
    """
    slug = _name_to_slug(problem_name)
    question = _fetch_problem(slug)

    if not question:
        return {
            "found": False,
            "slug_tried": slug,
            "error": (
                f"Problem '{problem_name}' (slug: '{slug}') not found on LeetCode. "
                "Try internet_search as a fallback."
            ),
        }

    return {
        "found": True,
        "title": question.get("title", problem_name),
        "difficulty": question.get("difficulty", "Unknown"),
        "tags": [t["name"] for t in (question.get("topicTags") or [])],
        "description": _strip_html(question.get("content", "")),
        "hints": question.get("hints") or [],
        "sample_input": question.get("sampleTestCase", ""),
        "example_testcases": question.get("exampleTestcases", ""),
    }
