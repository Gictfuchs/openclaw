"""Application lifecycle - bootstraps and runs all services."""

import asyncio
from pathlib import Path

import structlog

from openclaw.config import Settings
from openclaw.core.agent import FochsAgent
from openclaw.integrations.brave import BraveSearchClient
from openclaw.integrations.email import EmailClient, EmailConfig
from openclaw.integrations.github import GitHubClient
from openclaw.integrations.rss import RSSClient
from openclaw.llm.claude import ClaudeLLM
from openclaw.llm.gemini import GeminiLLM
from openclaw.llm.grok import GrokLLM
from openclaw.llm.ollama import OllamaLLM
from openclaw.llm.router import LLMRouter
from openclaw.research.engine import ResearchEngine
from openclaw.security.budget import TokenBudget
from openclaw.security.logging import setup_secure_logging
from openclaw.telegram.bot import FochsTelegramBot
from openclaw.tools.email_tools import ReadEmailsTool, SendEmailTool
from openclaw.tools.github_tools import GitHubCreateIssueTool, GitHubIssuesTool, GitHubRepoTool
from openclaw.tools.google_search import GoogleSearchTool
from openclaw.tools.registry import ToolRegistry
from openclaw.tools.rss_tools import CheckFeedTool
from openclaw.tools.web_scrape import WebScrapeTool
from openclaw.tools.web_search import WebSearchTool

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
        self.research: ResearchEngine | None = None
        self._brave: BraveSearchClient | None = None
        self._gemini: GeminiLLM | None = None
        self._scraper: WebScrapeTool | None = None

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
            self._gemini = gemini
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

        # Phase 2: Search & Research tools
        brave_key = self.settings.brave_api_key.get_secret_value()
        if brave_key:
            self._brave = BraveSearchClient(api_key=brave_key)
            registry.register(WebSearchTool(client=self._brave))
            logger.info("tool_configured", tool="web_search")

        if self._gemini:
            registry.register(GoogleSearchTool(gemini=self._gemini))
            logger.info("tool_configured", tool="google_search")

        self._scraper = WebScrapeTool()
        registry.register(self._scraper)
        logger.info("tool_configured", tool="web_scrape")

        # Phase 3: GitHub, Email, RSS tools
        gh_token = self.settings.github_token.get_secret_value()
        if gh_token:
            gh_client = GitHubClient(token=gh_token)
            registry.register(GitHubRepoTool(client=gh_client))
            registry.register(GitHubIssuesTool(client=gh_client))
            registry.register(GitHubCreateIssueTool(client=gh_client))
            logger.info("tool_configured", tool="github")

        if self.settings.email_address and self.settings.email_imap_host:
            email_client = EmailClient(EmailConfig(
                address=self.settings.email_address,
                password=self.settings.email_password.get_secret_value(),
                imap_host=self.settings.email_imap_host,
                smtp_host=self.settings.email_smtp_host,
            ))
            registry.register(ReadEmailsTool(client=email_client))
            if self.settings.email_smtp_host:
                registry.register(SendEmailTool(client=email_client))
            logger.info("tool_configured", tool="email")

        rss_client = RSSClient()
        registry.register(CheckFeedTool(client=rss_client))
        logger.info("tool_configured", tool="rss")

        # TODO Phase 4: memory_tools
        # TODO Phase 5: scheduler_tools
        # TODO Phase 6: sub_agent_tools

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

        # Research engine (uses Brave + Gemini + Scraper)
        self.research = ResearchEngine(
            llm=self.llm_router,
            brave=self._brave,
            gemini=self._gemini,
            scraper=self._scraper,
        )

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
                research=self.research,
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
