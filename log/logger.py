"""
Structured JSON logging for AlgoMentor.

Writes to three sinks:
  - stderr console     (INFO+, compact human-readable single-line)
  - algomentor.log     (DEBUG+, JSON, 10 MB rotating, 5 backups)
  - algomentor-error.log (ERROR+, JSON, 5 MB rotating, 3 backups)

JSON log record schema
----------------------
{
  "timestamp":   "2026-02-20T14:10:00.123456+00:00",
  "level":       "INFO",
  "logger":      "algomentor.core.agent_service",
  "request_id":  "a1b2c3d4-…",
  "user_id":     "123456789",
  "agent":       "AgentService",
  "stage":       "research",
  "duration_ms": 1420,
  "message":     "Research complete"
}

All application code retrieves loggers via:
    from log.logger import get_logger, log_event
    _logger = get_logger(__name__)
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG_DIR = Path(__file__).resolve().parent.parent
_LOG_FILE = _LOG_DIR / "algomentor.log"
_ERROR_LOG_FILE = _LOG_DIR / "algomentor-error.log"
_ROOT_LOGGER_NAME = "algomentor"

_CONSOLE_FORMAT = "[%(levelname)-8s] %(name)s — %(message)s"

_configured = False


# ── Context filter: inject default values for all structured fields ───────────

class _ContextFilter(logging.Filter):
    """Ensures every log record carries all structured fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        for attr, default in (
            ("user_id", "-"),
            ("request_id", "-"),
            ("agent", "-"),
            ("stage", "-"),
            ("duration_ms", None),
        ):
            if not hasattr(record, attr):
                setattr(record, attr, default)
        return True


# ── JSON formatter ────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """
    Serialises each log record to a single-line JSON object.

    All structured context fields are included when present.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "agent": getattr(record, "agent", "-"),
            "stage": getattr(record, "stage", "-"),
            "duration_ms": getattr(record, "duration_ms", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Drop None duration to keep logs tidy
        if payload["duration_ms"] is None:
            del payload["duration_ms"]
        return json.dumps(payload, ensure_ascii=False)


# ── One-time configuration ────────────────────────────────────────────────────

def _configure() -> None:
    global _configured
    if _configured:
        return

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(logging.DEBUG)

    ctx = _ContextFilter()
    json_fmt = _JsonFormatter()

    # ── Console: compact human-readable ──────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    console.addFilter(ctx)
    root.addHandler(console)

    # ── algomentor.log: all levels, JSON, 10 MB ───────────────────────────────
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(json_fmt)
    fh.addFilter(ctx)
    root.addHandler(fh)

    # ── algomentor-error.log: ERROR+ only, JSON, 5 MB ────────────────────────
    efh = logging.handlers.RotatingFileHandler(
        _ERROR_LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    efh.setLevel(logging.ERROR)
    efh.setFormatter(json_fmt)
    efh.addFilter(ctx)
    root.addHandler(efh)

    root.propagate = False
    _configured = True


# ── Public API ────────────────────────────────────────────────────────────────

def get_logger(name: str = "") -> logging.Logger:
    """
    Return a child logger under the 'algomentor' namespace.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    _configure()
    child = f"{_ROOT_LOGGER_NAME}.{name}" if name else _ROOT_LOGGER_NAME
    return logging.getLogger(child)


def log_event(
    logger: logging.Logger,
    message: str,
    level: int = logging.INFO,
    *,
    user_id: str = "-",
    request_id: str = "-",
    agent: str = "-",
    stage: str = "-",
    duration_ms: int | None = None,
) -> None:
    """
    Emit a structured log record with full pipeline context.

    All keyword arguments map directly to JSON log fields.

    Args:
        logger:      Logger instance (from :func:`get_logger`).
        message:     Human-readable log message.
        level:       stdlib logging level (default ``INFO``).
        user_id:     Telegram numeric ID or ``"cli"``.
        request_id:  UUID-v4 correlation token for this request.
        agent:       Name of the agent/class emitting the event.
        stage:       Pipeline stage label (e.g. ``"research"``).
        duration_ms: Elapsed milliseconds for timed stages.
    """
    extra: dict[str, Any] = {
        "user_id": user_id,
        "request_id": request_id,
        "agent": agent,
        "stage": stage,
    }
    if duration_ms is not None:
        extra["duration_ms"] = duration_ms
    logger.log(level, message, extra=extra)


class StageTimer:
    """
    Context manager that measures wall-clock duration of a pipeline stage
    and emits a structured log record on exit.

    Example::

        with StageTimer(logger, "research", user_id=uid, request_id=rid):
            result = do_heavy_work()
    """

    def __init__(
        self,
        logger: logging.Logger,
        stage: str,
        *,
        user_id: str = "-",
        request_id: str = "-",
        agent: str = "-",
    ) -> None:
        self._logger = logger
        self._stage = stage
        self._user_id = user_id
        self._request_id = request_id
        self._agent = agent
        self._start: float = 0.0

    def __enter__(self) -> "StageTimer":
        self._start = time.monotonic()
        log_event(
            self._logger,
            f"Stage started: {self._stage}",
            stage=self._stage,
            user_id=self._user_id,
            request_id=self._request_id,
            agent=self._agent,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed = int((time.monotonic() - self._start) * 1000)
        level = logging.ERROR if exc_type else logging.INFO
        log_event(
            self._logger,
            f"Stage {'failed' if exc_type else 'complete'}: {self._stage}",
            level=level,
            stage=self._stage,
            user_id=self._user_id,
            request_id=self._request_id,
            agent=self._agent,
            duration_ms=elapsed,
        )
        return False  # do not suppress exceptions
