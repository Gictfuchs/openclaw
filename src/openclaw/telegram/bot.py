"""Telegram bot setup and message handling."""

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from openclaw.core.agent import FochsAgent
from openclaw.core.events import ErrorEvent, ResponseEvent, ToolCallEvent

logger = structlog.get_logger()


class FochsTelegramBot:
    """Telegram bot interface for Fochs."""

    def __init__(
        self,
        token: str,
        agent: FochsAgent,
        allowed_users: list[int] | None = None,
    ) -> None:
        self.agent = agent
        self.allowed_users = allowed_users or []
        self.app: Application = ApplicationBuilder().token(token).build()  # type: ignore[assignment]
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("clear", self.cmd_clear))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message)
        )

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized."""
        if not self.allowed_users:
            return True  # No whitelist = allow all
        return user_id in self.allowed_users

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        await update.message.reply_text(
            "Hallo! Ich bin *Fochs*, dein autonomer KI-Agent. 🦊\n\n"
            "Schreib mir einfach eine Nachricht und ich helfe dir.\n"
            "Nutze /help für verfügbare Befehle.",
            parse_mode="Markdown",
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        await update.message.reply_text(
            "*Verfügbare Befehle:*\n\n"
            "/start - Begrüßung\n"
            "/help - Diese Hilfe\n"
            "/status - Agent-Status anzeigen\n"
            "/clear - Gesprächsverlauf löschen\n\n"
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
            icon = "✅" if available else "❌"
            provider_lines.append(f"  {icon} {name}")

        tools = status.get("tools", [])
        tools_text = ", ".join(tools) if tools else "keine"

        text = (
            f"*Fochs Status*\n\n"
            f"Status: {status.get('status', 'unknown')}\n"
            f"Aktive Gespräche: {status.get('active_conversations', 0)}\n\n"
            f"*LLM Provider:*\n" + "\n".join(provider_lines) + "\n\n"
            f"*Tools:* {tools_text}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        if not self._is_authorized(update.effective_user.id):
            return

        self.agent.clear_history(update.effective_user.id)
        await update.message.reply_text("Gesprächsverlauf gelöscht. ✨")

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle free-form text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        if not self._is_authorized(user_id):
            return

        logger.info("telegram_message", user_id=user_id, text_length=len(update.message.text))

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Process through agent
        response_parts: list[str] = []
        tool_notifications: list[str] = []

        async for event in self.agent.process(update.message.text, user_id):
            if isinstance(event, ToolCallEvent):
                tool_notifications.append(f"🔧 _{event.tool}_")
            elif isinstance(event, ResponseEvent):
                response_parts.append(event.content)
            elif isinstance(event, ErrorEvent):
                response_parts.append(f"⚠️ {event.message}")

        # Send tool usage notification if tools were used
        if tool_notifications:
            tools_text = "\n".join(tool_notifications)
            await update.message.reply_text(tools_text, parse_mode="Markdown")

        # Send the main response
        full_response = "\n".join(response_parts)
        if full_response:
            # Split long messages (Telegram limit: 4096 chars)
            for chunk in self._split_message(full_response):
                try:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    # Fallback without markdown if parsing fails
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
            # Try to split at a newline
            split_at = text.rfind("\n", 0, max_length)
            if split_at == -1:
                split_at = max_length
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def send_proactive_message(self, user_id: int, text: str) -> None:
        """Send a message to a user without them initiating."""
        try:
            await self.app.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("proactive_message_failed", user_id=user_id, error=str(e))
