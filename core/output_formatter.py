"""
OutputFormatter — post-processes raw LLM synthesis output into structured blocks.

Responsibilities:
 - Strip ** bold markers and ### / ## heading prefixes
 - Extract sections from the synthesised agent blob
 - Normalise pseudocode (remove language-specific syntax)
 - Explode similar-problems block into list[dict]
 - Return a structured dict consumed by AgentService._stream_idle

No external dependencies beyond the standard library.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Section heading patterns (mirrors agent_service._SECTION_PATTERNS) ────────

_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("Problem",          r"(?i)#+\s*Problem\b"),
    ("Constraints",      r"(?i)#+\s*Constraints?\b"),
    ("Statement",        r"(?i)#+\s*(Statement|Description|Problem Statement)\b"),
    ("Intuition",        r"(?i)#+\s*Intuition\b"),
    ("Approach",         r"(?i)#+\s*Approach\b"),
    ("Why This Works",   r"(?i)#+\s*Why\s+This\s+Works?\b"),
    ("Pseudocode",       r"(?i)#+\s*(Pseudocode|Pseudo[ -]code)\b"),
    ("Complexity",       r"(?i)#+\s*Complexity\b"),
    ("Similar Problems", r"(?i)(#+\s*Similar Problems?\b|🔗\s*SIMILAR PROBLEMS)"),
    ("Pattern",          r"(?i)(#+\s*Pattern\b|🧠\s*PATTERN)"),
    ("Learning Context", r"(?i)#+\s*(Learning Context|Learning|Context|Notes?|Optimization)\b"),
]

# Language keywords that betray real code (used to detect non-pseudocode blocks)
_LANG_KEYWORDS: tuple[str, ...] = (
    r"\bpublic\b", r"\bprivate\b", r"\bprotected\b",
    r"\bstatic\b", r"\bvoid\b", r"\bint\b", r"\blong\b",
    r"\bString\b", r"\bList\b", r"\bArrayList\b", r"\bHashMap\b",
    r"\bfun\b",        # Kotlin
    r"\bfn\b",         # Rust
    r"\bimport\s",     # Java / Python imports
    r"\bimport\b",
    r"#include",       # C/C++
    r"\busing\s+namespace\b",
    r"\bpackage\b",
    r"System\.out",
    r"println!",
    r"print\(",
    r"console\.log",
    r"::\s*[A-Z]",     # Rust type paths
)

_LANG_KEYWORD_RE = re.compile("|".join(_LANG_KEYWORDS))

# Tokens to strip when converting language code → pseudocode
_STRIP_TOKENS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(import|package|#include|using namespace)[^\n]*\n?", re.M), ""),
    (re.compile(r"\bpublic\b|\bprivate\b|\bprotected\b|\bstatic\b", re.M), ""),
    (re.compile(r"\b(?:void|int|long|double|float|boolean|bool|String|char)\b", re.M), ""),
    (re.compile(r"\b(?:ArrayList|HashMap|HashSet|TreeMap|TreeSet|List|Map|Set)<[^>]*>", re.M), ""),
    (re.compile(r"\b(?:new)\b", re.M), ""),
    (re.compile(r"[{}]", re.M), ""),
    (re.compile(r";", re.M), ""),
    (re.compile(r"@\w+\s*", re.M), ""),          # annotations / decorators
    (re.compile(r":\s*[A-Z]\w+(\s*\?)?\s*", re.M), " "),  # Kotlin/Rust types
    (re.compile(r"\s*->\s*\w+\s*\{?", re.M), ""),         # arrow return types
    (re.compile(r"^\s*\n", re.M), "\n"),          # collapse blank lines
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """Remove bold (**), italic (*), and heading prefixes (###, ##, #)."""
    # Remove heading lines (# Heading → Heading)
    text = re.sub(r"^#+\s+", "", text, flags=re.M)
    # Remove bold / italic markers
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    # Remove inline code backticks
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.M)
    # Remove link markdown [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Collapse runs of 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_raw_sections(text: str) -> dict[str, str]:
    """
    Split the synthesised blob into a dict keyed by canonical section name.

    If a heading appears multiple times, only the first occurrence is kept.
    """
    hits: list[tuple[int, str]] = []
    for title, pattern in _SECTION_PATTERNS:
        for m in re.finditer(pattern, text):
            hits.append((m.start(), title))
            break  # first occurrence per section type

    if not hits:
        return {"Analysis": text.strip()}

    hits.sort(key=lambda x: x[0])
    sections: dict[str, str] = {}
    for idx, (pos, title) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(text)
        raw = text[pos:end].strip()
        # Strip the leading heading line itself
        raw = re.sub(r"^[^\n]+\n?", "", raw, count=1).strip()
        sections[title] = raw
    return sections


# ── Public API ────────────────────────────────────────────────────────────────

# Required block keys that must be non-empty before delivery starts
_REQUIRED_BLOCKS: list[str] = [
    "problem",
    "constraints",
    "statement",
    "intuition",
    "approach",
    "why_this_works",
    "pseudocode",
    "complexity",
    "similar_problems",
    "notes",
]

_MIN_SIMILAR_PROBLEMS = 5


def validate_blocks(blocks: dict) -> tuple[bool, list[str]]:
    """
    Validate that all required sections are present and non-empty.

    For ``similar_problems``, at least 5 entries are required.

    Args:
        blocks: Dict returned by ``OutputFormatter.process()``.

    Returns:
        ``(True, [])`` when fully valid.
        ``(False, [missing_key, ...])`` listing every gap.
    """
    missing: list[str] = []
    for key in _REQUIRED_BLOCKS:
        value = blocks.get(key)
        if key == "similar_problems":
            count = len(value) if value else 0
            if count < _MIN_SIMILAR_PROBLEMS:
                missing.append(
                    f"similar_problems (got {count}, need {_MIN_SIMILAR_PROBLEMS})"
                )
        else:
            if not value or (isinstance(value, str) and not value.strip()):
                missing.append(key)
    return (len(missing) == 0, missing)


def convert_language_code_to_pseudocode(code: str) -> str:
    """
    Strip language-specific syntax from a code block and return clean pseudocode.

    Removes:
        - import / package / #include / using namespace lines
        - type annotations (int, String, List<T>, etc.)
        - Java / Kotlin / Rust visibility modifiers
        - braces, semicolons, decorators, arrow return types

    Args:
        code: Code block string (may or may not be inside triple-backtick fences).

    Returns:
        Multi-line pseudocode string.
    """
    # Strip code fences and language tags
    code = re.sub(r"```[\w]*\n?", "", code)
    code = re.sub(r"```", "", code)

    for pattern, replacement in _STRIP_TOKENS:
        code = pattern.sub(replacement, code)

    # Normalise indentation: each non-empty line gets 4-space indent preserved
    lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped:
            # Preserve relative indentation by counting leading spaces
            leading = len(line) - len(line.lstrip())
            indent = " " * min(leading, 12)
            lines.append(indent + stripped)
    return "\n".join(lines).strip()


def extract_similar_problems(text: str) -> list[dict]:
    """
    Parse the Similar Problems section into a list of dicts.

    Each entry must have a ``Platform:`` line.  Fields parsed:
        platform, title, url, reason

    Args:
        text: Raw similar-problems section content (heading already removed).

    Returns:
        List of dicts; empty list if no Platform: lines are found.
    """
    entries: list[dict] = []
    current: dict = {}
    field_map = {
        "platform": re.compile(r"(?i)^\s*platform\s*:\s*(.+)$"),
        "title":    re.compile(r"(?i)^\s*title\s*:\s*(.+)$"),
        "url":      re.compile(r"(?i)^\s*url\s*:\s*(.+)$"),
        "reason":   re.compile(r"(?i)^\s*(why similar|reason)\s*:\s*(.+)$"),
    }

    def _flush(d: dict) -> Optional[dict]:
        if d.get("platform"):
            return {
                "platform": d.get("platform", "").strip(),
                "title":    d.get("title", "").strip(),
                "url":      d.get("url", "").strip(),
                "reason":   d.get("reason", "").strip(),
            }
        return None

    for line in text.splitlines():
        if field_map["platform"].match(line):
            if current:
                entry = _flush(current)
                if entry:
                    entries.append(entry)
            current = {}

        for key, pat in field_map.items():
            m = pat.match(line)
            if m:
                if key == "reason":
                    current[key] = m.group(2)
                else:
                    current[key] = m.group(1)
                break

    if current:
        entry = _flush(current)
        if entry:
            entries.append(entry)

    return entries


def format_similar_problem_message(entry: dict) -> str:
    """
    Format a single similar-problem dict into a clean plain-text message.

    Args:
        entry: Dict with keys platform, title, url, reason.

    Returns:
        Plain-text string with no markdown.
    """
    lines = []
    if entry.get("platform"):
        lines.append(f"Platform: {entry['platform']}")
    if entry.get("title"):
        lines.append(f"Title: {entry['title']}")
    if entry.get("url"):
        lines.append(f"URL: {entry['url']}")
    if entry.get("reason"):
        lines.append(f"Why similar: {entry['reason']}")
    return "\n".join(lines)


class OutputFormatter:
    """
    Converts a raw LLM synthesis string into an ordered set of plain-text blocks.

    Usage::

        result = OutputFormatter().process(raw_agent_output)
        # result["problem"]          → str
        # result["approach"]         → str
        # result["pseudocode"]       → str
        # result["complexity"]       → str
        # result["similar_problems"] → list[dict]
        # result["notes"]            → str
    """

    def process(self, raw_text: str) -> dict:
        """
        Full pipeline — parse, clean, and structure the agent output.

        Args:
            raw_text: Synthesised response from RootAgent.

        Returns:
            Structured dict with all required keys:
            problem, constraints, statement, intuition, approach,
            why_this_works, pseudocode, complexity, similar_problems, notes,
            plus approach_combined (narrative block for delivery).
        """
        sections = _parse_raw_sections(raw_text)

        # Granular keys (each maps to exactly one logical block)
        problem_block     = self._build_problem_title_block(sections)
        constraints_block = self._build_constraints_block(sections)
        statement_block   = self._build_statement_block(sections)
        intuition_block   = self._build_intuition_block(sections)
        approach_block    = self._build_approach_only_block(sections)
        why_block         = self._build_why_block(sections)
        pseudocode_block  = self._build_pseudocode_block(sections)
        complexity_block  = self._build_complexity_block(sections)
        similar_problems  = self._build_similar_problems(sections)
        notes_block       = self._build_notes_block(sections)

        # Combined narrative (Statement + Intuition + Approach + Why) for Message 2
        narrative_parts = [p for p in [
            statement_block, intuition_block, approach_block, why_block
        ] if p and p.strip()]
        approach_combined = "\n\n".join(narrative_parts)

        return {
            "problem":           problem_block,
            "constraints":       constraints_block,
            "statement":         statement_block,
            "intuition":         intuition_block,
            "approach":          approach_block,
            "why_this_works":    why_block,
            "pseudocode":        pseudocode_block,
            "complexity":        complexity_block,
            "similar_problems":  similar_problems,
            "notes":             notes_block,
            # Combined narrative used by AgentService for delivery
            "approach_combined": approach_combined,
        }

    # ── Section builders ──────────────────────────────────────────────────────

    def _build_problem_title_block(self, sections: dict[str, str]) -> str:
        """Build the PROBLEM header: Title + Difficulty only (no constraints)."""
        raw = sections.get("Problem", "")
        if not raw:
            return ""
        cleaned = _strip_markdown(raw)
        title      = self._extract_field(cleaned, r"(?i)title\s*:\s*(.+)")
        difficulty = self._extract_field(cleaned, r"(?i)difficulty\s*:\s*(.+)")

        if not title:
            # Whole block is the description — use as-is
            return "PROBLEM\n\n" + cleaned

        parts = ["PROBLEM", f"Title: {title.strip()}"]
        if difficulty:
            parts.append(f"Difficulty: {difficulty.strip()}")
        return "\n".join(parts)

    def _build_constraints_block(self, sections: dict[str, str]) -> str:
        """
        Extract constraints text.

        Looks first for a dedicated Constraints section, then for a
        Constraints: field embedded inside the Problem section.
        """
        raw = sections.get("Constraints", "")
        if raw:
            return _strip_markdown(raw)
        # Fallback: inline Constraints: inside Problem
        problem_raw = _strip_markdown(sections.get("Problem", ""))
        return self._extract_field(
            problem_raw,
            r"(?i)constraints?\s*:\s*([\s\S]+?)$",
            multiline=True,
        ).strip()

    def _build_statement_block(self, sections: dict[str, str]) -> str:
        """
        Extract the problem statement / description text.

        Priority: dedicated Statement section → Description field in Problem
        → full Problem body (minus Title/Difficulty lines).
        """
        raw = sections.get("Statement", "")
        if raw:
            return _strip_markdown(raw)
        problem_raw = _strip_markdown(sections.get("Problem", ""))
        description = self._extract_field(
            problem_raw,
            r"(?i)description\s*:\s*([\s\S]+?)(?=\n\s*(?:constraint|$))",
            multiline=True,
        )
        if description:
            return description.strip()
        # Last resort: strip title/difficulty/constraints lines off the Problem block
        lines = [
            ln for ln in problem_raw.splitlines()
            if not re.match(r"(?i)^(title|difficulty|constraints?)\s*:", ln.strip())
        ]
        return "\n".join(lines).strip()

    def _build_intuition_block(self, sections: dict[str, str]) -> str:
        """Return the Intuition section, plain text."""
        raw = sections.get("Intuition", "")
        return _strip_markdown(raw) if raw else ""

    def _build_approach_only_block(self, sections: dict[str, str]) -> str:
        """Return the Approach section, plain text."""
        raw = sections.get("Approach", "")
        return _strip_markdown(raw) if raw else ""

    def _build_why_block(self, sections: dict[str, str]) -> str:
        """Return the Why This Works section, plain text."""
        raw = sections.get("Why This Works", "")
        return _strip_markdown(raw) if raw else ""

    def _build_pseudocode_block(self, sections: dict[str, str]) -> str:
        """
        Build clean algorithmic pseudocode.

        If the section contains language keywords, pass it through
        convert_language_code_to_pseudocode(); otherwise just strip markdown.
        """
        raw = sections.get("Pseudocode", "")
        if not raw:
            return ""

        if _LANG_KEYWORD_RE.search(raw):
            return convert_language_code_to_pseudocode(raw)

        # Strip markdown headings / bold but keep the structural lines
        cleaned = re.sub(r"^#+\s+", "", raw, flags=re.M)
        cleaned = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", cleaned)
        cleaned = re.sub(r"`([^`\n]+)`", r"\1", cleaned)
        cleaned = re.sub(r"```[\w]*\n?", "", cleaned)
        cleaned = re.sub(r"```", "", cleaned)
        return cleaned.strip()

    def _build_complexity_block(self, sections: dict[str, str]) -> str:
        """Build the COMPLEXITY block — Time and Space only, plain text."""
        raw = sections.get("Complexity", "")
        if not raw:
            return ""

        cleaned = _strip_markdown(raw)
        time_m  = re.search(r"(?i)time\s*(?:complexity)?\s*:?\s*(.+)", cleaned)
        space_m = re.search(r"(?i)space\s*(?:complexity)?\s*:?\s*(.+)", cleaned)

        if time_m or space_m:
            parts = []
            if time_m:
                parts.append(f"Time: {time_m.group(1).strip()}")
            if space_m:
                parts.append(f"Space: {space_m.group(1).strip()}")
            return "\n".join(parts)

        return cleaned

    def _build_similar_problems(self, sections: dict[str, str]) -> list[dict]:
        """Parse the Similar Problems section into list[dict]."""
        raw = sections.get("Similar Problems", "")
        if not raw:
            return []
        cleaned = _strip_markdown(raw)
        return extract_similar_problems(cleaned)

    def _build_notes_block(self, sections: dict[str, str]) -> str:
        """Combine Pattern and Learning Context into a single NOTES block."""
        parts: list[str] = []
        for key in ("Pattern", "Learning Context"):
            raw = sections.get(key, "")
            if raw:
                parts.append(_strip_markdown(raw))
        return "\n\n".join(p for p in parts if p).strip()

    # ── Field extraction utility ──────────────────────────────────────────────

    @staticmethod
    def _extract_field(
        text: str,
        pattern: str,
        multiline: bool = False,
    ) -> str:
        """Return the first capture group from pattern, or empty string."""
        flags = re.M if multiline else 0
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else ""
