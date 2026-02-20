"""
Tool: content_extractor
Fetches a URL and returns clean, readable plain text — stripping HTML tags,
scripts, styles, and boilerplate navigation.  Used by subagents to extract
full editorial / discussion content from search results.
"""
from __future__ import annotations

import re
import urllib.request
import urllib.error
from html.parser import HTMLParser

from langchain_core.tools import tool


# ── HTML → plain text ─────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Minimal HTML parser that collects visible text, skipping noisy tags."""

    SKIP_TAGS = {
        "script", "style", "head", "nav", "footer", "header",
        "aside", "noscript", "svg", "img", "input", "button", "form",
    }

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        raw = " ".join(self._parts)
        # Collapse excessive whitespace
        raw = re.sub(r"\s{3,}", "\n\n", raw)
        return raw.strip()


def _fetch_text(url: str, max_chars: int = 4000) -> str:
    """Download URL and return plain text (truncated to max_chars)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        return f"ERROR fetching {url}: {exc}"

    parser = _TextExtractor()
    parser.feed(raw_html)
    text = parser.get_text()
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


# ── LangChain tool ────────────────────────────────────────────────────────────

@tool
def content_extractor(url: str, max_chars: int = 4000) -> dict:
    """
    Fetch a web page and return extracted plain text suitable for LLM consumption.

    Strips all HTML tags, scripts, styles, and noisy navigation elements.
    Returns at most `max_chars` characters to stay within context limits.

    Args:
        url:       The full URL to fetch (http or https).
        max_chars: Maximum number of characters to return (default 4000).

    Returns:
        Dict with keys:
            url       — the URL that was fetched
            text      — extracted plain text content
            truncated — True if the content was cut off
    """
    if not url.startswith(("http://", "https://")):
        return {"url": url, "text": "ERROR: URL must start with http:// or https://", "truncated": False}

    full_text = _fetch_text(url, max_chars)
    truncated = full_text.endswith("…")
    return {
        "url": url,
        "text": full_text,
        "truncated": truncated,
    }
