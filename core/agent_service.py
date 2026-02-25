"""
AgentService — transport-agnostic conversation orchestrator.

Wraps RootAgent with:
- Per-user session state (idle → awaiting approval → awaiting language)
- Human-in-the-loop enforcement
- Stage-based streaming via async generator (handle_message_stream)
- AgentEvent emission at every pipeline stage
- UUID v4 request correlation propagated through the full pipeline
- Structured JSON logging with per-stage duration_ms

Session states
--------------
IDLE                  Waiting for a problem name.
AWAITING_APPROVAL     Research delivered; waiting for yes/no.
AWAITING_LANGUAGE     User approved; waiting for language choice.

Streaming contract
------------------
Both transports (CLI and Telegram) drive the pipeline exclusively through
``handle_message_stream()``, which yields :class:`~core.events.AgentEvent`
objects in order:

  progress events  →  section events  →  complete (or error) event

Example::

    async for event in service.handle_message_stream(user_id, text):
        if event.stage == "section":
            print(f"## {event.section_title}\\n{event.payload}")
        elif event.stage in STAGE_MESSAGES:
            print(f"[{event.stage}] {event.payload}")
        elif event.stage == "error":
            print(f"Error: {event.payload}")
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import AsyncIterator, Optional

from core.events import AgentEvent, STAGE_MESSAGES
from core.output_formatter import (
    OutputFormatter,
    format_similar_problem_message,
    validate_blocks,
)
from log.logger import get_logger, log_event

_logger = get_logger(__name__)


# ── Research pipeline stages in order ────────────────────────────────────────
# Emitted as timed progress events while the blocking thread executes.
# Approximate wall-clock delays (seconds from thread start).
_RESEARCH_STAGES: list[tuple[float, str]] = [
    (0.0,  "fetch"),
    (8.0,  "similar"),
    (16.0, "patterns"),
    (24.0, "solutions"),
    (32.0, "strategy"),
    (40.0, "synthesis"),
]

# ── Output section titles to look for in synthesised text ─────────────────────
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("Problem",          r"(?i)#+\s*Problem\b"),
    ("Intuition",        r"(?i)#+\s*Intuition\b"),
    ("Pseudocode",       r"(?i)#+\s*(Pseudocode|Pseudo[ -]code)\b"),
    ("Complexity",       r"(?i)#+\s*Complexity\b"),
    # Match both markdown heading and legacy emoji-prefixed format from synthesis prompt
    ("Similar Problems", r"(?i)(#+\s*Similar Problems?\b|🔗\s*SIMILAR PROBLEMS)"),
    ("Pattern",          r"(?i)(#+\s*Pattern\b|🧠\s*PATTERN)"),
    ("Learning Context", r"(?i)#+\s*(Learning Context|Learning|Context)\b"),
]

# ── Session state machine ─────────────────────────────────────────────────────

class _State(Enum):
    IDLE = auto()
    AWAITING_APPROVAL = auto()
    AWAITING_LANGUAGE = auto()


@dataclass
class _Session:
    """Conversation state for one user."""

    state: _State = _State.IDLE
    problem_name: Optional[str] = None
    research_output: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

_LANG_PROMPT = (
    "Which language would you like the solution in?\n"
    "Options: python / java / cpp / go / typescript"
)


def _new_request_id() -> str:
    """Generate a UUID-v4 correlation token for one user request."""
    return str(uuid.uuid4())


# ── Similarity problem entry delay ──────────────────────────────────────────
_SIMILAR_ENTRY_DELAY_S: float = 0.4  # 400 ms between individual problem entries

# ── Recovery prompt injected when synthesis is incomplete ────────────────────
_RECOVERY_PROMPT_TEMPLATE = """\
{problem_name}

IMPORTANT: Your previous response was incomplete. Regenerate a FULL structured \
solution with ALL of the following sections:

## Problem
## Constraints
## Statement
## Intuition
## Approach
## Why This Works
## Pseudocode
## Complexity
## Similar Problems
## Notes

Rules:
- No markdown bold or stars
- No emojis
- Similar Problems MUST include exactly one problem from EACH of these platforms:
  Codeforces, CodeChef, GeeksForGeeks, HackerRank, LeetCode
- Each Similar Problem entry MUST have: Platform, Title, URL, Why similar
- Return FULL content for every section — no placeholders
"""


def _parse_similar_problems(text: str) -> list[str]:
    """
    Split a Similar Problems block into individual problem entries.

    Each entry starts with a ``Platform:`` line and contains four fields:
    Platform, Title, URL, Why similar.  Any preamble before the first
    ``Platform:`` line (e.g. the section heading) is discarded.

    Args:
        text: Raw similar-problems section content.

    Returns:
        List of formatted entry strings; empty list if none found.
    """
    entries: list[str] = []
    current: list[str] = []
    inside_entry = False  # ignore preamble before the first Platform: line

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("platform:"):
            if inside_entry and current:
                # Flush the previous entry
                entry = "\n".join(ln for ln in current if ln.strip())
                if entry:
                    entries.append(entry)
            current = [stripped]
            inside_entry = True
        elif inside_entry and stripped:
            current.append(stripped)

    if inside_entry and current:
        entry = "\n".join(ln for ln in current if ln.strip())
        if entry:
            entries.append(entry)

    return entries


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """
    Parse a synthesised response into titled sections.

    Splits on recognised markdown headings.  If no headings are found the
    entire text is returned as a single ``"Analysis"`` section.

    Args:
        text: Full synthesised agent output.

    Returns:
        Ordered list of ``(title, content)`` tuples.
    """
    hits: list[tuple[int, str]] = []
    for title, pattern in _SECTION_PATTERNS:
        for m in re.finditer(pattern, text):
            hits.append((m.start(), title))

    if not hits:
        return [("Analysis", text.strip())]

    hits.sort(key=lambda x: x[0])
    sections: list[tuple[str, str]] = []
    for idx, (pos, title) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(text)
        content = text[pos:end].strip()
        sections.append((title, content))
    return sections


# ── Service ───────────────────────────────────────────────────────────────────


class AgentService:
    """
    Transport-agnostic conversation manager for AlgoMentor.

    Both CLI and Telegram call ``handle_message_stream``; the service maintains
    independent state for each ``user_id``.

    Attributes:
        sessions: Per-user ``_Session`` dict keyed by user_id string.
    """

    def __init__(self) -> None:
        from agent.deep_agent import build_root_agent

        log_event(
            _logger,
            "Initialising RootAgent",
            stage="startup",
            agent="AgentService",
        )
        self._agent = build_root_agent()
        self.sessions: dict[str, _Session] = {}
        log_event(
            _logger,
            "AgentService ready",
            stage="startup",
            agent="AgentService",
        )

    # ── Primary streaming API ─────────────────────────────────────────────────

    async def handle_message_stream(
        self,
        user_id: str,
        message: str,
    ) -> AsyncIterator[AgentEvent]:
        """
        Process one inbound user message and yield :class:`AgentEvent` objects.

        Progress events are yielded as each pipeline stage begins; section
        events carry parsed output blocks; a final ``complete`` or ``error``
        event closes the stream.

        Blocking LLM/network calls are offloaded via ``asyncio.to_thread``.

        Args:
            user_id: Telegram numeric ID string or ``"cli"``.
            message: Raw text received from the user.

        Yields:
            :class:`~core.events.AgentEvent` in emission order.
        """
        request_id = _new_request_id()
        session = self.sessions.setdefault(user_id, _Session())
        message = message.strip()

        log_event(
            _logger,
            f"Request received: {message!r}  state={session.state.name}",
            user_id=user_id,
            request_id=request_id,
            agent="AgentService",
            stage="router",
        )

        if session.state is _State.IDLE:
            async for event in self._stream_idle(user_id, request_id, session, message):
                yield event
        elif session.state is _State.AWAITING_APPROVAL:
            async for event in self._stream_approval(user_id, request_id, session, message):
                yield event
        elif session.state is _State.AWAITING_LANGUAGE:
            async for event in self._stream_language(user_id, request_id, session, message):
                yield event
        else:
            session.state = _State.IDLE
            yield AgentEvent.error(
                user_id, request_id, "Session reset. Please send a problem name."
            )

    # ── Backward-compatible non-streaming API ─────────────────────────────────

    async def handle_message(self, user_id: str, message: str) -> str:
        """
        Non-streaming wrapper — collects all events and returns a single string.

        Kept for compatibility; prefer ``handle_message_stream`` in new code.

        Args:
            user_id: Telegram numeric ID string or ``"cli"``.
            message: Raw text received from the user.

        Returns:
            Concatenated reply text.
        """
        parts: list[str] = []
        async for event in self.handle_message_stream(user_id, message):
            if event.stage == "section":
                parts.append(event.payload)
            elif event.stage == "error":
                parts.append(event.payload)
            elif event.stage == "complete" and not parts:
                parts.append(event.payload)
        return "\n\n".join(parts) if parts else ""

    def reset_session(self, user_id: str) -> None:
        """Force-reset a user's session to IDLE (for ``/reset`` commands)."""
        self.sessions.pop(user_id, None)
        log_event(
            _logger,
            "Session reset",
            user_id=user_id,
            agent="AgentService",
            stage="router",
        )

    # ── State stream handlers ─────────────────────────────────────────────────

    async def _stream_idle(
        self,
        user_id: str,
        request_id: str,
        session: _Session,
        problem_name: str,
    ) -> AsyncIterator[AgentEvent]:
        """Stream research progress events then parsed output sections."""
        session.problem_name = problem_name
        session.state = _State.AWAITING_APPROVAL

        log_event(
            _logger,
            f"Starting research: {problem_name!r}",
            user_id=user_id,
            request_id=request_id,
            agent="AgentService",
            stage="research",
        )

        t0 = time.monotonic()
        loop = asyncio.get_running_loop()
        research_task: asyncio.Task = loop.create_task(
            asyncio.to_thread(self._agent.research_problem, problem_name)
        )

        # Emit ordered progress events; each fires as soon as the stage timer
        # expires OR when research finishes, whichever comes first.
        for delay, stage in _RESEARCH_STAGES:
            remaining = max(0.0, delay - (time.monotonic() - t0))
            try:
                done, _ = await asyncio.wait({research_task}, timeout=remaining)
            except asyncio.CancelledError:
                research_task.cancel()
                raise

            yield AgentEvent.progress(user_id, request_id, stage)  # type: ignore[arg-type]
            log_event(
                _logger,
                f"Stage emitted: {stage}",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage=stage,
            )
            if research_task.done():
                break

        try:
            research: str = await research_task
        except Exception as exc:
            _logger.error(
                "research_problem failed: %s",
                exc,
                extra={
                    "user_id": user_id,
                    "request_id": request_id,
                    "stage": "research",
                    "agent": "AgentService",
                },
                exc_info=True,
            )
            session.state = _State.IDLE
            yield AgentEvent.error(
                user_id,
                request_id,
                f"Sorry, I hit an error researching '{problem_name}': {exc}",
            )
            return

        duration_ms = int((time.monotonic() - t0) * 1000)
        log_event(
            _logger,
            "Research complete",
            user_id=user_id,
            request_id=request_id,
            agent="AgentService",
            stage="research",
            duration_ms=duration_ms,
        )

        session.research_output = research

        # ── Post-process through OutputFormatter ─────────────────────────────
        formatter = OutputFormatter()
        structured = formatter.process(research)
        is_valid, missing = validate_blocks(structured)

        if not is_valid:
            # Log every missing block
            for key in missing:
                _logger.error(
                    "block_missing=%s",
                    key,
                    extra={
                        "user_id": user_id,
                        "request_id": request_id,
                        "stage": "validation",
                        "agent": "AgentService",
                    },
                )
            log_event(
                _logger,
                f"Incomplete synthesis — retrying ({len(missing)} missing blocks)",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="validation",
            )

            # Emit a progress marker so the user isn't left silent
            yield AgentEvent.progress(user_id, request_id, "synthesis")  # type: ignore[arg-type]

            recovery_query = _RECOVERY_PROMPT_TEMPLATE.format(
                problem_name=problem_name
            )
            try:
                research_retry: str = await asyncio.to_thread(
                    self._agent.research_problem, recovery_query
                )
            except Exception as exc:
                _logger.error(
                    "recovery research_problem failed: %s",
                    exc,
                    extra={
                        "user_id": user_id,
                        "request_id": request_id,
                        "stage": "recovery",
                        "agent": "AgentService",
                    },
                    exc_info=True,
                )
                session.state = _State.IDLE
                yield AgentEvent.error(
                    user_id,
                    request_id,
                    f"Sorry, recovery synthesis failed for '{problem_name}': {exc}",
                )
                return

            structured = formatter.process(research_retry)
            session.research_output = research_retry
            is_valid_retry, missing_retry = validate_blocks(structured)

            if not is_valid_retry:
                for key in missing_retry:
                    _logger.error(
                        "block_missing=%s (after retry)",
                        key,
                        extra={
                            "user_id": user_id,
                            "request_id": request_id,
                            "stage": "validation_retry",
                            "agent": "AgentService",
                        },
                    )
                log_event(
                    _logger,
                    "Synthesis still incomplete after retry — delivering best-effort",
                    user_id=user_id,
                    request_id=request_id,
                    agent="AgentService",
                    stage="validation_retry",
                )
            else:
                log_event(
                    _logger,
                    "Recovery synthesis complete — all blocks present",
                    user_id=user_id,
                    request_id=request_id,
                    agent="AgentService",
                    stage="validation_retry",
                )

        # ── Staged delivery (only begins after validation guard) ──────────────

        # MESSAGE 1: Problem + Constraints
        problem_text = structured["problem"]
        constraints_text = structured["constraints"]
        if problem_text or constraints_text:
            msg1_parts = []
            if problem_text:
                msg1_parts.append(problem_text)
            if constraints_text:
                msg1_parts.append("Constraints:\n" + constraints_text)
            yield AgentEvent.section(
                user_id, request_id, "Problem", "\n\n".join(msg1_parts)
            )
            log_event(
                _logger,
                "Section delivered",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="problem_sent",
            )
            await asyncio.sleep(0.3)

        # MESSAGE 2: Statement + Intuition + Approach + Why This Works
        approach_text = structured["approach_combined"]
        if approach_text:
            yield AgentEvent.section(user_id, request_id, "Approach", approach_text)
            log_event(
                _logger,
                "Section delivered",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="statement_sent",
            )
            await asyncio.sleep(0.3)

        # MESSAGE 3: Pseudocode only
        pseudocode_text = structured["pseudocode"]
        if pseudocode_text:
            yield AgentEvent.section(user_id, request_id, "Pseudocode", pseudocode_text)
            log_event(
                _logger,
                "Section delivered",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="pseudocode_sent",
            )
            await asyncio.sleep(0.3)

        # MESSAGE 4: Complexity
        complexity_text = structured["complexity"]
        if complexity_text:
            yield AgentEvent.section(user_id, request_id, "Complexity", complexity_text)
            log_event(
                _logger,
                "Section delivered",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="complexity_sent",
            )
            await asyncio.sleep(0.3)

        # MESSAGES 5+: Similar problems — one per message
        similar_problems = structured["similar_problems"]
        if similar_problems:
            for i, prob in enumerate(similar_problems):
                msg_text = format_similar_problem_message(prob)
                yield AgentEvent.section(
                    user_id, request_id, "Similar Problem", msg_text
                )
                log_event(
                    _logger,
                    f"Similar problem delivered: {prob.get('platform', '?')} — {prob.get('title', '?')}",
                    user_id=user_id,
                    request_id=request_id,
                    agent="AgentService",
                    stage="similar_problem_sent",
                )
                if i < len(similar_problems) - 1:
                    await asyncio.sleep(_SIMILAR_ENTRY_DELAY_S)
        else:
            # Fallback: no structured entries found — search for raw similar block
            for title, content in _parse_sections(research):
                if title == "Similar Problems":
                    entries = _parse_similar_problems(content)
                    for i, entry in enumerate(entries):
                        yield AgentEvent.section(
                            user_id, request_id, "Similar Problem", entry
                        )
                        log_event(
                            _logger,
                            "Similar problem delivered (fallback)",
                            user_id=user_id,
                            request_id=request_id,
                            agent="AgentService",
                            stage="similar_problem_sent",
                        )
                        if i < len(entries) - 1:
                            await asyncio.sleep(_SIMILAR_ENTRY_DELAY_S)
                    break
        await asyncio.sleep(0.3)

        # Notes / Optimization Insights
        notes_text = structured["notes"]
        if notes_text:
            yield AgentEvent.section(user_id, request_id, "Notes", notes_text)
            await asyncio.sleep(0.3)

        # Prompt for code generation
        yield AgentEvent.section(
            user_id,
            request_id,
            "Next Step",
            "Generate code? yes or no",
        )
        yield AgentEvent.complete(user_id, request_id)

    async def _stream_approval(
        self,
        user_id: str,
        request_id: str,
        session: _Session,
        reply: str,
    ) -> AsyncIterator[AgentEvent]:
        """Handle yes/no response to the code-generation gate."""
        lower = reply.lower()

        if lower in ("yes", "y"):
            session.state = _State.AWAITING_LANGUAGE
            log_event(
                _logger,
                "Code generation approved",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="approval",
            )
            yield AgentEvent.section(user_id, request_id, "Language", _LANG_PROMPT)
            yield AgentEvent.complete(user_id, request_id)
            return

        if lower in ("no", "n", "skip"):
            session.state = _State.IDLE
            log_event(
                _logger,
                "Code generation skipped",
                user_id=user_id,
                request_id=request_id,
                agent="AgentService",
                stage="approval",
            )
            yield AgentEvent.section(
                user_id,
                request_id,
                "Session",
                "Skipping code generation. Send another problem name whenever you are ready.",
            )
            yield AgentEvent.complete(user_id, request_id)
            return

        yield AgentEvent.section(
            user_id, request_id, "Prompt", "Please reply yes or no."
        )
        yield AgentEvent.complete(user_id, request_id)

    async def _stream_language(
        self,
        user_id: str,
        request_id: str,
        session: _Session,
        language: str,
    ) -> AsyncIterator[AgentEvent]:
        """Generate and stream code in the requested language."""
        if not language.strip():
            yield AgentEvent.section(user_id, request_id, "Language", _LANG_PROMPT)
            yield AgentEvent.complete(user_id, request_id)
            return

        language = language.strip().lower()
        problem_name = session.problem_name or ""
        research_output = session.research_output or ""

        t0 = time.monotonic()
        log_event(
            _logger,
            f"Generating {language} solution for {problem_name!r}",
            user_id=user_id,
            request_id=request_id,
            agent="AgentService",
            stage="codegen",
        )

        # Keep transport active immediately
        yield AgentEvent.progress(user_id, request_id, "synthesis")  # type: ignore[arg-type]

        try:
            code: str = await asyncio.to_thread(
                self._agent.generate_code,
                problem_name,
                language,
                research_output,
            )
        except Exception as exc:
            _logger.error(
                "generate_code failed: %s",
                exc,
                extra={
                    "user_id": user_id,
                    "request_id": request_id,
                    "stage": "codegen",
                    "agent": "AgentService",
                },
                exc_info=True,
            )
            session.state = _State.IDLE
            yield AgentEvent.error(
                user_id,
                request_id,
                f"Sorry, code generation failed: {exc}",
            )
            return

        duration_ms = int((time.monotonic() - t0) * 1000)
        log_event(
            _logger,
            "Code generation complete",
            user_id=user_id,
            request_id=request_id,
            agent="AgentService",
            stage="codegen",
            duration_ms=duration_ms,
        )

        session.state = _State.IDLE
        log_event(
            _logger,
            f"Code delivered: {language}",
            user_id=user_id,
            request_id=request_id,
            agent="AgentService",
            stage="code_generated",
        )
        yield AgentEvent.section(
            user_id,
            request_id,
            f"Solution ({language.title()})",
            code,
        )
        yield AgentEvent.complete(user_id, request_id)
