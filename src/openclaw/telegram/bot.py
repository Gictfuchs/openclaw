"""Telegram bot setup and message handling."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from openclaw.core.events import ErrorEvent, ResponseEvent, ToolCallEvent
from openclaw.db.engine import get_session
from openclaw.memory.models import WatcherState, WatchSubscription

if TYPE_CHECKING:
    from telegram import Update

    from openclaw.config import Settings
    from openclaw.core.agent import FochsAgent
    from openclaw.research.engine import ResearchEngine

logger = structlog.get_logger()

# Rate limit: max messages per user per minute
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0


class FochsTelegramBot:
    """Telegram bot interface for Fochs."""

    def __init__(
        self,
        token: str,
        agent: FochsAgent,
        allowed_users: list[int] | None = None,
        research: ResearchEngine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.agent = agent
        self.allowed_users = allowed_users or []
        self.research = research
        self.settings = settings
        self.app: Application = ApplicationBuilder().token(token).build()  # type: ignore[assignment]
        self._rate_tracker: dict[int, list[float]] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("clear", self.cmd_clear))
        self.app.add_handler(CommandHandler("research", self.cmd_research))
        self.app.add_handler(CommandHandler("watch", self.cmd_watch))
        self.app.add_handler(CommandHandler("unwatch", self.cmd_unwatch))
        self.app.add_handler(CommandHandler("watches", self.cmd_watches))
        self.app.add_handler(CommandHandler("autonomy", self.cmd_autonomy))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is in the whitelist. Empty list = deny all."""
        if not self.allowed_users:
            return False
        return user_id in self.allowed_users

    def _is_rate_limited(self, user_id: int) -> bool:
        """Check if user has exceeded rate limit."""
        now = time.monotonic()
        timestamps = self._rate_tracker.get(user_id, [])
        timestamps = [t for t in timestamps if now - t < _RATE_WINDOW]
        if len(timestamps) >= _RATE_LIMIT:
            self._rate_tracker[user_id] = timestamps
            return True
        timestamps.append(now)
        self._rate_tracker[user_id] = timestamps
        return False

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            logger.warning("unauthorized_access", user_id=update.effective_user.id)
            return

        await update.message.reply_text(
            "Hallo! Ich bin *Fochs*, dein autonomer KI-Agent.\n\n"
            "Schreib mir einfach eine Nachricht und ich helfe dir.\n"
            "Nutze /help fuer verfuegbare Befehle.",
            parse_mode="Markdown",
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        await update.message.reply_text(
            "*Verfuegbare Befehle:*\n\n"
            "/start - Begruessung\n"
            "/help - Diese Hilfe\n"
            "/status - Agent-Status anzeigen\n"
            "/research <thema> - Tiefe Recherche\n"
            "/watch <typ> <ziel> - Thema/Repo/Feed ueberwachen\n"
            "/unwatch <id> - Watch deaktivieren\n"
            "/watches - Aktive Watches anzeigen\n"
            "/autonomy <level> - Autonomie: full/ask/manual\n"
            "/clear - Gespraechsverlauf loeschen\n\n"
            "Oder schreib einfach eine Nachricht!",
            parse_mode="Markdown",
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        status = await self.agent.get_status()

        providers = status.get("llm_providers", {})
        provider_lines = []
        for name, available in providers.items():
            icon = "+" if available else "-"
            provider_lines.append(f"  {icon} {name}")

        tools = status.get("tools", [])
        tools_text = ", ".join(tools) if tools else "keine"

        budget = status.get("budget", {})
        budget_text = ""
        if budget:
            budget_text = (
                f"\n\n*Budget:*\n"
                f"  Heute: {budget.get('daily_usage', 0):,} / {budget.get('daily_limit', 0):,} tokens\n"
                f"  Monat: {budget.get('monthly_usage', 0):,} / {budget.get('monthly_limit', 0):,} tokens"
            )
            if budget.get("killed"):
                budget_text += "\n  KILL SWITCH AKTIV"

        text = (
            f"*Fochs Status*\n\n"
            f"Status: {status.get('status', 'unknown')}\n"
            f"Aktive Gespraeche: {status.get('active_conversations', 0)}\n\n"
            f"*LLM Provider:*\n" + "\n".join(provider_lines) + "\n\n"
            f"*Tools:* {tools_text}"
            f"{budget_text}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        self.agent.clear_history(update.effective_user.id)
        await update.message.reply_text("Gespraechsverlauf geloescht.")

    async def cmd_research(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /research <topic> command."""
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return
        if self._is_rate_limited(update.effective_user.id):
            await update.message.reply_text("Zu viele Nachrichten. Bitte warte kurz.")
            return

        if not self.research:
            await update.message.reply_text("Research Engine ist nicht konfiguriert.")
            return

        # Extract topic from command arguments
        topic = " ".join(context.args) if context.args else ""
        if not topic:
            await update.message.reply_text("Bitte gib ein Thema an: /research <thema>")
            return

        logger.info("research_command", user_id=update.effective_user.id, topic=topic)
        await update.message.reply_text(f"Recherchiere: _{topic}_...", parse_mode="Markdown")
        await update.message.chat.send_action("typing")

        try:
            result = await self.research.research(topic)
            report = result.format()

            for chunk in self._split_message(report):
                try:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(chunk)
        except Exception as e:
            logger.error("research_command_failed", error=str(e))
            await update.message.reply_text(f"Recherche fehlgeschlagen: {e}")

    async def cmd_watch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /watch <type> <target> command."""
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text(
                "Nutzung: /watch <typ> <ziel>\n\n"
                "Typen: topic, github, rss, email\n"
                "Beispiele:\n"
                "  /watch topic KI Regulierung\n"
                "  /watch github owner/repo\n"
                "  /watch rss https://example.com/feed\n"
                "  /watch email inbox"
            )
            return

        watcher_type = args[0].lower()
        valid_types = {"topic", "github", "rss", "email"}
        if watcher_type not in valid_types:
            await update.message.reply_text(f"Ungueltiger Typ. Erlaubt: {', '.join(sorted(valid_types))}")
            return

        target = " ".join(args[1:])
        user_id = update.effective_user.id

        async with get_session() as session:
            sub = WatchSubscription(user_id=user_id, watcher_type=watcher_type, target=target)
            session.add(sub)
            await session.flush()
            session.add(WatcherState(subscription_id=sub.id))
            await session.commit()
            sub_id = sub.id

        await update.message.reply_text(f"Watch #{sub_id} erstellt: [{watcher_type}] {target}")

    async def cmd_unwatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /unwatch <id> command."""
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        args = context.args or []
        if not args or not args[0].isdigit():
            await update.message.reply_text("Nutzung: /unwatch <id>")
            return

        sub_id = int(args[0])
        async with get_session() as session:
            result = await session.execute(select(WatchSubscription).where(WatchSubscription.id == sub_id))
            sub = result.scalar_one_or_none()
            if not sub:
                await update.message.reply_text(f"Watch #{sub_id} nicht gefunden.")
                return
            sub.active = False
            await session.commit()

        await update.message.reply_text(f"Watch #{sub_id} deaktiviert.")

    async def cmd_watches(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /watches command - list active watches."""
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        user_id = update.effective_user.id
        async with get_session() as session:
            result = await session.execute(
                select(WatchSubscription).where(
                    WatchSubscription.user_id == user_id,
                    WatchSubscription.active.is_(True),
                )
            )
            subs = list(result.scalars().all())

        if not subs:
            await update.message.reply_text("Keine aktiven Watches.")
            return

        lines = ["*Aktive Watches:*\n"]
        for sub in subs:
            lines.append(f"#{sub.id} [{sub.watcher_type}] {sub.target}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def cmd_autonomy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /autonomy <level> command."""
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        args = context.args or []
        valid_levels = {"full", "ask", "manual"}

        if not args or args[0].lower() not in valid_levels:
            current = self.settings.autonomy_level if self.settings else "unknown"
            await update.message.reply_text(
                f"Aktuelles Level: *{current}*\n\nNutzung: /autonomy <level>\nLevel: full, ask, manual",
                parse_mode="Markdown",
            )
            return

        level = args[0].lower()
        if self.settings:
            self.settings.autonomy_level = level  # type: ignore[assignment]
            logger.info("autonomy_level_changed", user_id=update.effective_user.id, level=level)
        await update.message.reply_text(
            f"Autonomie-Level auf *{level}* gesetzt.\n_(Gilt bis zum naechsten Neustart)_",
            parse_mode="Markdown",
        )

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle free-form text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        if not self._is_authorized(user_id):
            return

        if self._is_rate_limited(user_id):
            await update.message.reply_text("Zu viele Nachrichten. Bitte warte kurz.")
            return

        logger.info("telegram_message", user_id=user_id, text_length=len(update.message.text))

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Process through agent
        response_parts: list[str] = []
        tool_notifications: list[str] = []

        async for event in self.agent.process(update.message.text, user_id):
            if isinstance(event, ToolCallEvent):
                tool_notifications.append(f"Tool: {event.tool}")
            elif isinstance(event, ResponseEvent):
                response_parts.append(event.content)
            elif isinstance(event, ErrorEvent):
                response_parts.append(f"Fehler: {event.message}")

        # Send tool usage notification if tools were used
        if tool_notifications:
            tools_text = "\n".join(tool_notifications)
            await update.message.reply_text(tools_text)

        # Send the main response
        full_response = "\n".join(response_parts)
        if full_response:
            for chunk in self._split_message(full_response):
                try:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(chunk)

    @staticmethod
    def _split_message(text: str, max_length: int = 4000) -> list[str]:
        """Split a message into chunks for Telegram."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, max_length)
            if split_at == -1:
                split_at = max_length
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def send_proactive_message(self, user_id: int, text: str) -> None:
        """Send a message to a user without them initiating."""
        if not self._is_authorized(user_id):
            logger.warning("proactive_unauthorized", user_id=user_id)
            return
        try:
            await self.app.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("proactive_message_failed", user_id=user_id, error=str(e))
