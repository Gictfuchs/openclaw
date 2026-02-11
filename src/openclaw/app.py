"""Application lifecycle - bootstraps and runs all services."""

import asyncio
from pathlib import Path

import structlog

from openclaw.config import Settings
from openclaw.core.agent import FochsAgent
from openclaw.db.engine import close_db, init_db
from openclaw.integrations.brave import BraveSearchClient
from openclaw.integrations.email import EmailClient, EmailConfig
from openclaw.integrations.github import GitHubClient
from openclaw.integrations.rss import RSSClient
from openclaw.llm.claude import ClaudeLLM
from openclaw.llm.gemini import GeminiLLM
from openclaw.llm.grok import GrokLLM
from openclaw.llm.ollama import OllamaLLM
from openclaw.llm.router import LLMRouter
from openclaw.memory.long_term import LongTermMemory
from openclaw.memory.vector_store import VectorStore
from openclaw.plugins.loader import PluginLoader
from openclaw.research.engine import ResearchEngine
from openclaw.scheduler.manager import SchedulerManager
from openclaw.security.budget import TokenBudget
from openclaw.security.logging import setup_secure_logging
from openclaw.security.shell_guard import ShellGuard
from openclaw.sub_agents.runner import SubAgentRunner
from openclaw.telegram.bot import FochsTelegramBot
from openclaw.tools.delegate_tool import DelegateTool
from openclaw.tools.email_tools import ReadEmailsTool, SendEmailTool
from openclaw.tools.file_tool import FileReadTool, FileWriteTool
from openclaw.tools.github_tools import GitHubCreateIssueTool, GitHubIssuesTool, GitHubRepoTool
from openclaw.tools.google_search import GoogleSearchTool
from openclaw.tools.memory_tools import RecallMemoryTool, StoreMemoryTool
from openclaw.tools.registry import ToolRegistry
from openclaw.tools.rss_tools import CheckFeedTool
from openclaw.tools.scheduler_tools import ListWatchesTool, UnwatchTool, WatchTool
from openclaw.tools.self_update_tool import SelfUpdateTool
from openclaw.tools.shell_tool import ShellExecuteTool
from openclaw.tools.web_scrape import WebScrapeTool
from openclaw.tools.web_search import WebSearchTool
from openclaw.web.server import start_web_server

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
        self.memory: LongTermMemory | None = None
        self.scheduler: SchedulerManager | None = None
        self.sub_agent_runner: SubAgentRunner | None = None
        self._brave: BraveSearchClient | None = None
        self._gemini: GeminiLLM | None = None
        self._scraper: WebScrapeTool | None = None
        self._github: GitHubClient | None = None
        self._email: EmailClient | None = None
        self._rss: RSSClient | None = None
        self._shell_guard: ShellGuard | None = None
        self._plugin_loader: PluginLoader | None = None

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
            registry.register(WebSearchTool(client=self._brave), core=True)
            logger.info("tool_configured", tool="web_search")

        if self._gemini:
            registry.register(GoogleSearchTool(gemini=self._gemini), core=True)
            logger.info("tool_configured", tool="google_search")

        self._scraper = WebScrapeTool()
        registry.register(self._scraper, core=True)
        logger.info("tool_configured", tool="web_scrape")

        # Phase 3: GitHub, Email, RSS tools
        gh_token = self.settings.github_token.get_secret_value()
        if gh_token:
            self._github = GitHubClient(token=gh_token)
            registry.register(GitHubRepoTool(client=self._github), core=True)
            registry.register(GitHubIssuesTool(client=self._github), core=True)
            registry.register(GitHubCreateIssueTool(client=self._github), core=True)
            logger.info("tool_configured", tool="github")

        if self.settings.email_address and self.settings.email_imap_host:
            self._email = EmailClient(
                EmailConfig(
                    address=self.settings.email_address,
                    password=self.settings.email_password.get_secret_value(),
                    imap_host=self.settings.email_imap_host,
                    smtp_host=self.settings.email_smtp_host,
                )
            )
            registry.register(ReadEmailsTool(client=self._email), core=True)
            if self.settings.email_smtp_host:
                registry.register(SendEmailTool(client=self._email), core=True)
            logger.info("tool_configured", tool="email")

        self._rss = RSSClient()
        registry.register(CheckFeedTool(client=self._rss), core=True)
        logger.info("tool_configured", tool="rss")

        # Phase 5: Scheduler tools
        registry.register(WatchTool(), core=True)
        registry.register(UnwatchTool(), core=True)
        registry.register(ListWatchesTool(), core=True)
        logger.info("tool_configured", tool="scheduler")

        # Phase 8: Shell, File, Self-Update tools
        self._shell_guard = ShellGuard(
            mode=self.settings.shell_mode,
            allowed_dirs=self.settings.shell_allowed_dirs,
        )
        registry.register(
            ShellExecuteTool(
                guard=self._shell_guard,
                default_timeout=self.settings.shell_timeout,
            ),
            core=True,
        )
        registry.register(FileReadTool(guard=self._shell_guard), core=True)
        registry.register(FileWriteTool(guard=self._shell_guard), core=True)
        registry.register(SelfUpdateTool(guard=self._shell_guard), core=True)
        logger.info(
            "tool_configured",
            tool="shell_suite",
            mode=self.settings.shell_mode,
        )

        # Phase 4: Memory tools (registered after memory is initialized in start())
        # Phase 6: Delegate tool (registered after sub-agent runner is initialized in start())

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

        # Setup token budget (with persistence across restarts)
        budget_path = str(Path(self.settings.data_dir) / "budget_state.json")
        self.budget = TokenBudget(
            daily_limit=self.settings.daily_token_budget,
            monthly_limit=self.settings.monthly_token_budget,
            per_run_limit=self.settings.max_tokens_per_run,
            persist_path=budget_path,
        )

        # Setup components
        self.llm_router = self._setup_llm()
        self.llm_router.budget = self.budget
        self.tools = self._setup_tools()

        # Initialize database and memory
        await init_db(self.settings.db_path)
        vector_store = VectorStore(persist_dir=self.settings.chroma_path)
        self.memory = LongTermMemory(vector_store=vector_store)
        logger.info("memory_initialized", db=self.settings.db_path, vectors=self.settings.chroma_path)

        # Register memory tools (needs memory to be initialized first)
        self.tools.register(RecallMemoryTool(memory=self.memory), core=True)
        self.tools.register(StoreMemoryTool(memory=self.memory), core=True)
        logger.info("tool_configured", tool="memory")

        # Phase 6: Sub-agent runner + delegation tool
        self.sub_agent_runner = SubAgentRunner(llm=self.llm_router, tools=self.tools)
        self.tools.register(DelegateTool(runner=self.sub_agent_runner), core=True)
        logger.info("tool_configured", tool="delegate")

        # Phase 8: Plugin loader (hot-reload custom tools)
        self._plugin_loader = PluginLoader(
            plugins_dir=self.settings.plugins_dir,
            registry=self.tools,
        )
        loaded_plugins = self._plugin_loader.scan_and_load()
        if loaded_plugins:
            logger.info("plugins_loaded", tools=loaded_plugins)

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
            memory=self.memory,
        )

        # Check LLM availability
        availability = await self.llm_router.check_availability()
        for provider, available in availability.items():
            status = "available" if available else "unavailable"
            logger.info("llm_status", provider=provider, status=status)

        # Build app_state dict for web dashboard
        app_state = {
            "agent": self.agent,
            "scheduler": self.scheduler,  # May be set below
            "sub_agent_runner": self.sub_agent_runner,
        }

        # Start Telegram bot
        token = self.settings.telegram_bot_token.get_secret_value()
        if token:
            self.telegram = FochsTelegramBot(
                token=token,
                agent=self.agent,
                allowed_users=self.settings.telegram_allowed_users,
                research=self.research,
                settings=self.settings,
            )
            logger.info("telegram_bot_starting")
            await self.telegram.app.initialize()
            await self.telegram.app.start()
            await self.telegram.app.updater.start_polling()  # type: ignore[union-attr]

            # Start scheduler (background watchers)
            self.scheduler = SchedulerManager(
                telegram=self.telegram,
                settings=self.settings,
                brave=self._brave,
                github=self._github,
                rss=self._rss,
                email=self._email,
            )
            await self.scheduler.start()
            app_state["scheduler"] = self.scheduler

            logger.info("fochs_ready", telegram=True)
        else:
            logger.warning(
                "no_telegram_token",
                msg="FOCHS_TELEGRAM_BOT_TOKEN not set - running web dashboard only",
            )

        # Start web dashboard (runs in background)
        web_task = asyncio.create_task(
            start_web_server(self.settings, app_state),
            name="web_dashboard",
        )
        # Log if the web task fails unexpectedly
        web_task.add_done_callback(self._on_background_task_done)

        # Keep running
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("fochs_shutting_down")
        finally:
            web_task.cancel()
            if self.scheduler:
                await self.scheduler.stop()
            if self.telegram:
                await self.telegram.app.updater.stop()  # type: ignore[union-attr]
                await self.telegram.app.stop()
                await self.telegram.app.shutdown()
            await close_db()

    @staticmethod
    def _on_background_task_done(task: asyncio.Task[None]) -> None:
        """Callback for background tasks — log exceptions instead of losing them."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(
                "background_task_failed",
                task_name=task.get_name(),
                error=str(exc),
                exc_type=type(exc).__name__,
            )
