"""
Telegram transport layer.

Uses python-telegram-bot v20+ async polling.

UX contract:
  - A progress placeholder is sent within the first second of any request.
  - That placeholder is edited (not re-sent) as each pipeline stage completes.
  - Each parsed output section is delivered as an independent message.
  - Large sections (> 4 096 chars) are split to comply with Telegram limits.
  - The bot never stays silent for more than ~8 seconds (first progress event
    fires at t=0 before the blocking thread starts).

The session state machine lives entirely in AgentService; this module is a
pure I/O adapter.
"""
from __future__ import annotations

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.agent_service import AgentService
from core.events import AgentEvent, STAGE_MESSAGES
from log.logger import get_logger, log_event

_logger = get_logger(__name__)

_TELEGRAM_MSG_LIMIT = 4096

# Stage → emoji shown while the progress placeholder is being updated
_STAGE_EMOJI: dict[str, str] = {
    "fetch":     "📥",
    "similar":   "🔍",
    "patterns":  "🧩",
    "solutions": "⛏",
    "strategy":  "🏆",
    "synthesis": "🔗",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _split_message(text: str, limit: int = _TELEGRAM_MSG_LIMIT) -> list[str]:
    """
    Split text into chunks that fit within Telegram's per-message limit.

    Attempts to split on newlines first; falls back to hard slicing.

    Args:
        text:  Input string.
        limit: Maximum characters per chunk (default 4 096).

    Returns:
        List of non-empty string chunks.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to break on a newline boundary
        split_at = text.rfind("\n", 0, limit)
        split_at = split_at if split_at > limit // 2 else limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return [c for c in chunks if c.strip()]


async def _send(update: Update, text: str) -> list[Message]:
    """
    Send a reply split across multiple messages if necessary.
    Link previews are always suppressed.

    Args:
        update: Telegram Update object.
        text:   Text to send.

    Returns:
        List of sent :class:`telegram.Message` objects.
    """
    sent: list[Message] = []
    for chunk in _split_message(text):
        msg = await update.message.reply_text(  # type: ignore[union-attr]
            chunk,
            disable_web_page_preview=True,
        )
        sent.append(msg)
    return sent


async def _edit_or_send(
    update: Update,
    placeholder: Message | None,
    text: str,
) -> Message | None:
    """
    Edit an existing placeholder message, or send a new one if editing fails.

    Args:
        update:      Telegram Update object (fallback send target).
        placeholder: Message to edit; ``None`` triggers a fresh send.
        text:        New message text.

    Returns:
        The placeholder (edited or original) for future edits.
    """
    if placeholder is None:
        msgs = await _send(update, text)
        return msgs[0] if msgs else None
    try:
        await placeholder.edit_text(text, disable_web_page_preview=True)
        return placeholder
    except BadRequest:
        # Text unchanged or message too old to edit — silently skip
        return placeholder

# ── Handler factories ─────────────────────────────────────────────────────────
def _build_handlers(service: AgentService):
    """Return (start_handler, reset_handler, message_handler)."""

    async def cmd_start(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user_id = str(update.effective_user.id)  # type: ignore[union-attr]
        log_event(_logger, "/start received", user_id=user_id, stage="telegram")
        await _send(
            update,
            (
                "Hi! I'm AlgoMentor.\n"
                "Send me a LeetCode problem name and I'll explain it.\n\n"
                "Example: Number of Islands"
            ),
        )

    async def cmd_reset(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user_id = str(update.effective_user.id)  # type: ignore[union-attr]
        service.reset_session(user_id)
        log_event(_logger, "/reset received", user_id=user_id, stage="telegram")
        await _send(update, "Session reset. Send a problem name to start fresh.")

    async def on_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not update.message or not update.message.text:
            return

        user_id = str(update.effective_user.id)  # type: ignore[union-attr]
        text = update.message.text.strip()

        log_event(
            _logger,
            f"Message received: {text!r}",
            user_id=user_id,
            stage="telegram",
        )

        # ── Reusable progress placeholder ─────────────────────────────────────
        # Sent on the first progress event; edited on subsequent ones;
        # deleted when the first section message arrives.
        progress_msg: Message | None = None
        section_count: int = 0

        try:
            async for event in service.handle_message_stream(user_id, text):
                if event.stage in STAGE_MESSAGES:
                    # Progress notification
                    emoji = _STAGE_EMOJI.get(event.stage, "⏳")
                    status_text = f"{emoji}  {event.payload}"
                    progress_msg = await _edit_or_send(
                        update, progress_msg, status_text
                    )

                elif event.stage == "section":
                    # Delete the progress placeholder on first section
                    if progress_msg is not None and section_count == 0:
                        try:
                            await progress_msg.delete()
                        except BadRequest:
                            pass  # already deleted or can't delete
                        progress_msg = None

                    section_count += 1
                    # Plain-text header — no markdown, no parse_mode
                    if event.section_title:
                        header = f"── {event.section_title} ──\n\n"
                    else:
                        header = ""
                    body = header + event.payload
                    await _send(update, body)

                elif event.stage == "complete":
                    # Clean up any lingering placeholder
                    if progress_msg is not None:
                        try:
                            await progress_msg.delete()
                        except BadRequest:
                            pass
                        progress_msg = None

                elif event.stage == "error":
                    if progress_msg is not None:
                        try:
                            await progress_msg.delete()
                        except BadRequest:
                            pass
                        progress_msg = None
                    await _send(update, f"⚠️  {event.payload}")

        except Exception as exc:
            _logger.error(
                "handle_message_stream error: %s",
                exc,
                extra={"user_id": user_id, "stage": "telegram"},
                exc_info=True,
            )
            await _send(update, f"Sorry, something went wrong: {exc}")

        log_event(
            _logger,
            f"Exchange complete ({section_count} sections)",
            user_id=user_id,
            stage="telegram",
        )

    return cmd_start, cmd_reset, on_message

# ── Entry point ───────────────────────────────────────────────────────────────
def run(service: AgentService) -> None:
    """
    Build and start the Telegram bot using a webhook.

    Listens on 0.0.0.0:8080 and registers the webhook URL with Telegram.
    Blocks until interrupted (Ctrl-C or SIGTERM).

    Requires env vars:
        TELEGRAM_BOT_TOKEN  — bot token issued by @BotFather.
        PUBLIC_URL          — HTTPS base URL reachable by Telegram
                              (e.g. https://myapp.fly.dev).

    Args:
        service: Shared AgentService instance already initialised by main.py.
    """
    from config.settings import TELEGRAM_BOT_TOKEN, PUBLIC_URL

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — add it to your .env file."
        )

    log_event(_logger, "Starting Telegram bot (webhook mode)", stage="startup")

    cmd_start, cmd_reset, on_message = _build_handlers(service)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{TELEGRAM_BOT_TOKEN}"
    log_event(_logger, f"Webhook URL: {webhook_url}", stage="startup")

    app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
    )
