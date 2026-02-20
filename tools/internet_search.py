"""
Tool: internet_search
Wraps Tavily for web search. Used as the fallback when LeetCode scraper
cannot find a problem (e.g. custom problems or company OA questions).
"""
from typing import Literal

from langchain_core.tools import tool
from tavily import TavilyClient

from config.settings import TAVILY_API_KEY

_client = TavilyClient(api_key=TAVILY_API_KEY)


@tool
def internet_search(
    query: str,
    max_results: int = 6,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
) -> dict:
    """
    Search the internet for algorithm problems, explanations, and solutions.

    Use this when:
    - The LeetCode scraper fails to find a problem.
    - Additional context (editorial, patterns, similar problems) is needed.
    - Searching Codeforces, GeeksForGeeks, or other competitive-programming sites.

    Args:
        query: Natural-language search query.
        max_results: How many results to return (1-10).
        topic: Search category — keep "general" for algorithm queries.
        include_raw_content: Return full page text alongside snippets.

    Returns:
        Dict with keys: query, results (list of {url, title, content, score}).
    """
    response = _client.search(
        query=query,
        max_results=max_results,
        topic=topic,
        include_raw_content=include_raw_content,
    )
    # Trim to the essentials so we don't blow up the context window
    trimmed = {
        "query": response.get("query", query),
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content", "")[:800],
            }
            for r in response.get("results", [])
        ],
    }
    return trimmed
