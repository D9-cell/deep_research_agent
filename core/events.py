"""
AgentEvent — typed event emitted at every pipeline stage.

Events flow from AgentService → transport layers (CLI / Telegram).
Transports subscribe by passing an async callback to handle_message_stream().

Stage labels (ordered):
    fetch        → problem acquisition
    similar      → similarity discovery
    patterns     → pattern classification
    solutions    → solution mining
    strategy     → strategy optimisation
    synthesis    → root-LLM synthesis
    section      → one parsed output section
    complete     → final stage, pipeline done
    error        → unrecoverable error
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# Canonical stage labels used across the entire pipeline
StageLabel = Literal[
    "fetch",
    "similar",
    "patterns",
    "solutions",
    "strategy",
    "synthesis",
    "section",
    "complete",
    "error",
]

# Human-readable progress messages shown to users
STAGE_MESSAGES: dict[str, str] = {
    "fetch":     "Problem Acquisition started",
    "similar":   "Similarity search running",
    "patterns":  "Pattern classification complete",
    "solutions": "Strategy ranking complete",
    "strategy":  "Synthesizing solution strategy",
    "synthesis": "Finalizing response",
}


@dataclass
class AgentEvent:
    """
    Single event emitted during agent pipeline execution.

    Attributes:
        user_id:    Originating user identifier (Telegram ID or "cli").
        request_id: UUID-v4 string linking all events for one user request.
        stage:      Pipeline stage that produced this event.
        payload:    Human-readable text content for this event.
        timestamp:  ISO-8601 UTC timestamp of emission.
        section_title: Non-empty only when stage == "section"; names the block.
    """

    user_id: str
    request_id: str
    stage: StageLabel
    payload: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    section_title: str = ""

    # ── Convenience constructors ──────────────────────────────────────────────

    @classmethod
    def progress(
        cls,
        user_id: str,
        request_id: str,
        stage: StageLabel,
    ) -> "AgentEvent":
        """Emit a labelled progress notification with the canonical stage message."""
        return cls(
            user_id=user_id,
            request_id=request_id,
            stage=stage,
            payload=STAGE_MESSAGES.get(stage, stage),
        )

    @classmethod
    def section(
        cls,
        user_id: str,
        request_id: str,
        title: str,
        content: str,
    ) -> "AgentEvent":
        """Emit one named output section (Problem, Intuition, Pseudocode, …)."""
        return cls(
            user_id=user_id,
            request_id=request_id,
            stage="section",
            payload=content,
            section_title=title,
        )

    @classmethod
    def complete(
        cls,
        user_id: str,
        request_id: str,
        payload: str = "",
    ) -> "AgentEvent":
        """Signal pipeline completion."""
        return cls(
            user_id=user_id,
            request_id=request_id,
            stage="complete",
            payload=payload or "Analysis complete.",
        )

    @classmethod
    def error(
        cls,
        user_id: str,
        request_id: str,
        payload: str,
    ) -> "AgentEvent":
        """Signal an unrecoverable pipeline error."""
        return cls(
            user_id=user_id,
            request_id=request_id,
            stage="error",
            payload=payload,
        )
