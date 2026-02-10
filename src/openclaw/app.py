"""Application lifecycle - bootstraps and runs all services."""

import asyncio
from pathlib import Path

import structlog

from openclaw.config import Settings
from openclaw.core.agent import FochsAgent
from openclaw.llm.claude import ClaudeLLM
from openclaw.llm.gemini import GeminiLLM
from openclaw.llm.grok import GrokLLM
from openclaw.llm.ollama import OllamaLLM
from openclaw.llm.router import LLMRouter
from openclaw.security.budget import TokenBudget
from openclaw.security.logging import setup_secure_logging
from openclaw.telegram.bot import FochsTelegramBot
from openclaw.tools.registry import ToolRegistry

logger = structlog.get_logger()


class FochsApp:
    """Main application that wires everything together."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.llm_router: LLMRouter | None = None
        self.tools: ToolRegistry | None = None
        self.agent: FochsAgent | None = None
        self.telegram: FochsTelegramBot | None = None
        self.budget: TokenBudget | None = None

    def _ensure_data_dirs(self) -> None:
        """Create data directories if they don't exist."""
        for path in [self.settings.data_dir, self.settings.chroma_path, self.settings.log_dir]:
            Path(path).mkdir(parents=True, exist_ok=True)

    def _setup_llm(self) -> LLMRouter:
        """Initialize LLM providers and router."""
        claude = None
        ollama = None
        gemini = None
        grok = None

        if self.settings.anthropic_api_key.get_secret_value():
            claude = ClaudeLLM(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                model=self.settings.anthropic_model,
            )
            logger.info("llm_provider_configured", provider="claude", model=self.settings.anthropic_model)

        if self.settings.ollama_host:
            ollama = OllamaLLM(
                host=self.settings.ollama_host,
                model=self.settings.ollama_default_model,
            )
            logger.info("llm_provider_configured", provider="ollama", model=self.settings.ollama_default_model)

        if self.settings.gemini_api_key.get_secret_value():
            gemini = GeminiLLM(
                api_key=self.settings.gemini_api_key.get_secret_value(),
                model=self.settings.gemini_model,
            )
            logger.info("llm_provider_configured", provider="gemini", model=self.settings.gemini_model)

        if self.settings.xai_api_key.get_secret_value():
            grok = GrokLLM(
                api_key=self.settings.xai_api_key.get_secret_value(),
                model=self.settings.xai_model,
            )
            logger.info("llm_provider_configured", provider="grok", model=self.settings.xai_model)

        return LLMRouter(claude=claude, ollama=ollama, gemini=gemini, grok=grok)

    def _setup_tools(self) -> ToolRegistry:
        """Initialize and register tools."""
        registry = ToolRegistry()
        # Tools will be registered in later phases:
        # - Phase 2: web_search, google_search, web_scrape, social_media
        # - Phase 3: github, email, calendar, rss
        # - Phase 4: memory_tools
        # - Phase 5: scheduler_tools
        # - Phase 6: sub_agent_tools
        return registry

    async def start(self) -> None:
        """Start the application."""
        setup_secure_logging()
        self._ensure_data_dirs()

        logger.info("fochs_starting", version="0.1.0")

        # Startup security checks
        if not self.settings.telegram_allowed_users:
            logger.warning(
                "security_warning",
                msg="FOCHS_TELEGRAM_ALLOWED_USERS is empty - bot will reject all messages. "
                "Set your Telegram user ID to allow access.",
            )

        # Setup token budget
        self.budget = TokenBudget(
            daily_limit=self.settings.daily_token_budget,
            monthly_limit=self.settings.monthly_token_budget,
            per_run_limit=self.settings.max_tokens_per_run,
        )

        # Setup components
        self.llm_router = self._setup_llm()
        self.llm_router.budget = self.budget
        self.tools = self._setup_tools()
        self.agent = FochsAgent(
            llm=self.llm_router,
            tools=self.tools,
            max_iterations=self.settings.max_iterations,
        )

        # Check LLM availability
        availability = await self.llm_router.check_availability()
        for provider, available in availability.items():
            status = "available" if available else "unavailable"
            logger.info("llm_status", provider=provider, status=status)

        # Start Telegram bot
        token = self.settings.telegram_bot_token.get_secret_value()
        if token:
            self.telegram = FochsTelegramBot(
                token=token,
                agent=self.agent,
                allowed_users=self.settings.telegram_allowed_users,
            )
            logger.info("telegram_bot_starting")
            await self.telegram.app.initialize()
            await self.telegram.app.start()
            await self.telegram.app.updater.start_polling()  # type: ignore[union-attr]
            logger.info("fochs_ready", telegram=True)

            # Keep running
            try:
                await asyncio.Event().wait()
            except (KeyboardInterrupt, SystemExit):
                logger.info("fochs_shutting_down")
            finally:
                await self.telegram.app.updater.stop()  # type: ignore[union-attr]
                await self.telegram.app.stop()
                await self.telegram.app.shutdown()
        else:
            logger.error("no_telegram_token", msg="Set FOCHS_TELEGRAM_BOT_TOKEN in .env")
