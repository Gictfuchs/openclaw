"""Health-check diagnostics — ``fochs doctor``.

Performs a sequence of checks to verify the Fochs installation is
correctly configured and all services are reachable.  Designed to
be run after ``fochs setup`` or when troubleshooting.
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openclaw.config import Settings

from openclaw.cli.output import (
    BOLD,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    header,
    info,
)
from openclaw.cli.output import (
    err as _err_print,
)
from openclaw.cli.output import (
    ok as _ok_print,
)
from openclaw.cli.output import (
    warn as _warn_print,
)


class DoctorReport:
    """Collects check results for a summary at the end."""

    def __init__(self) -> None:
        self.passed: int = 0
        self.warnings: int = 0
        self.errors: int = 0

    def ok(self, msg: str) -> None:
        _ok_print(msg)
        self.passed += 1

    def warn(self, msg: str) -> None:
        _warn_print(msg)
        self.warnings += 1

    def err(self, msg: str) -> None:
        _err_print(msg)
        self.errors += 1

    @property
    def total(self) -> int:
        return self.passed + self.warnings + self.errors


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_system(report: DoctorReport) -> None:
    """Check system prerequisites."""
    header("System")

    # Python version
    v = sys.version_info
    if v >= (3, 12):
        report.ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        report.err(f"Python {v.major}.{v.minor}.{v.micro} — need 3.12+")

    # OS
    report.ok(f"{platform.system()} {platform.machine()} ({platform.release()})")

    # Required tools
    for cmd, label in [("uv", "uv package manager"), ("git", "Git")]:
        if shutil.which(cmd):
            report.ok(f"{label} found")
        else:
            report.err(f"{label} not found")


def _check_config(report: DoctorReport) -> Settings | None:
    """Validate configuration. Returns Settings object if valid."""
    header("Configuration")

    # Check .env file
    project_dir = Path.cwd()
    env_path = project_dir / ".env"
    if env_path.is_file():
        report.ok(f".env file found ({env_path.stat().st_size} bytes)")
    else:
        report.err(f".env file not found at {env_path}")
        info("Run 'fochs setup' to create one")
        return None

    # Try loading settings
    try:
        from openclaw.config import Settings

        settings = Settings()
        report.ok("Pydantic Settings loaded")
    except Exception as e:
        report.err(f"Settings validation failed: {e}")
        return None

    # Check individual settings
    if settings.anthropic_api_key.get_secret_value():
        report.ok("Anthropic API key configured")
    else:
        report.err("Anthropic API key missing — no LLM available")

    if settings.telegram_bot_token.get_secret_value():
        report.ok("Telegram bot token configured")
    else:
        report.warn("Telegram bot token missing — bot mode disabled")

    if settings.telegram_allowed_users:
        report.ok(f"Telegram allowed users: {len(settings.telegram_allowed_users)} user(s)")
    elif settings.telegram_bot_token.get_secret_value():
        report.warn("Telegram allowed users empty — bot will reject all messages")

    if settings.brave_api_key.get_secret_value():
        report.ok("Brave Search API key configured")
    else:
        report.warn("Brave Search key missing — web search disabled")

    if settings.github_token.get_secret_value():
        report.ok("GitHub token configured")
    else:
        info("GitHub token not set (optional)")

    # Budget settings
    report.ok(
        f"Budget: {settings.daily_token_budget:,}/day, "
        f"{settings.monthly_token_budget:,}/month, "
        f"{settings.max_tokens_per_run:,}/run"
    )

    # Shell mode
    report.ok(f"Shell mode: {settings.shell_mode}")
    if settings.shell_mode == "unrestricted":
        report.warn("Unrestricted shell — agent has full system access")

    return settings


def _check_directories(report: DoctorReport, settings: Settings) -> None:
    """Check data directories."""
    header("Directories")

    data_dir = Path(settings.data_dir)
    if data_dir.is_dir():
        report.ok(f"Data directory: {data_dir}")
    else:
        report.warn(f"Data directory does not exist yet: {data_dir} (will be created on first start)")

    chroma_path = Path(settings.chroma_path)
    if chroma_path.is_dir():
        report.ok(f"ChromaDB directory: {chroma_path}")
    else:
        info(f"ChromaDB directory will be created: {chroma_path}")

    plugins_dir = Path(settings.plugins_dir)
    if plugins_dir.is_dir():
        py_files = list(plugins_dir.glob("*.py"))
        non_private = [f for f in py_files if not f.name.startswith("_")]
        report.ok(f"Plugins directory: {plugins_dir} ({len(non_private)} plugin file(s))")
    else:
        info(f"Plugins directory: {plugins_dir} (not created yet)")


async def _check_llm(report: DoctorReport, settings: Settings) -> None:
    """Check LLM provider connectivity."""
    header("LLM Providers")

    from openclaw.llm.claude import ClaudeLLM
    from openclaw.llm.router import LLMRouter

    claude = None
    if settings.anthropic_api_key.get_secret_value():
        claude = ClaudeLLM(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
        )

    # Only test Claude — Gemini/Ollama are optional fallbacks
    router = LLMRouter(claude=claude)

    try:
        availability = await router.check_availability()
        for provider, available in availability.items():
            if available:
                report.ok(f"{provider}: reachable")
            else:
                if provider == "claude":
                    report.err(f"{provider}: unreachable")
                else:
                    info(f"{provider}: not configured (optional)")
    except Exception as e:
        report.err(f"LLM connectivity check failed: {e}")


async def _check_database(report: DoctorReport, settings: Settings) -> None:
    """Check database connectivity."""
    header("Database")

    db_path = Path(settings.db_path)
    if db_path.is_file():
        size_kb = db_path.stat().st_size / 1024
        report.ok(f"SQLite database: {db_path} ({size_kb:.1f} KB)")
    else:
        info(f"Database will be created on first start: {db_path}")

    # Try to import and check
    try:
        from openclaw.db.engine import close_db, init_db

        await init_db(str(db_path))
        report.ok("Database engine initialized successfully")
        await close_db()
    except Exception as e:
        report.err(f"Database initialization failed: {e}")


def _check_budget_state(report: DoctorReport, settings: Settings) -> None:
    """Check budget state file."""
    header("Token Budget")

    budget_path = Path(settings.data_dir) / "budget_state.json"
    if budget_path.is_file():
        import json

        try:
            data = json.loads(budget_path.read_text(encoding="utf-8"))
            daily = data.get("daily_usage", 0)
            monthly = data.get("monthly_usage", 0)
            report.ok(f"Budget state: {daily:,} daily / {monthly:,} monthly tokens used")
            if daily > settings.daily_token_budget * 0.8:
                report.warn(f"Daily budget >80% used ({daily:,}/{settings.daily_token_budget:,})")
            if monthly > settings.monthly_token_budget * 0.8:
                report.warn(f"Monthly budget >80% used ({monthly:,}/{settings.monthly_token_budget:,})")
        except Exception as e:
            report.warn(f"Could not read budget state: {e}")
    else:
        info("No budget state file yet (will be created on first API call)")


def _check_optional_integrations(report: DoctorReport, settings: Settings) -> None:
    """Report optional integration status."""
    header("Optional Integrations")

    integrations = [
        ("Composio", bool(settings.composio_api_key.get_secret_value())),
        ("ClawHub", bool(settings.clawhub_api_key.get_secret_value())),
        ("VirusTotal", bool(settings.virustotal_api_key.get_secret_value())),
        ("Honcho", bool(settings.honcho_api_key.get_secret_value())),
        ("AgentMail", bool(settings.agentmail_api_key.get_secret_value())),
        ("Email (IMAP)", bool(settings.email_address and settings.email_imap_host)),
    ]

    configured = sum(1 for _, v in integrations if v)
    info(f"{configured}/{len(integrations)} optional integrations configured")

    for name, active in integrations:
        if active:
            report.ok(f"{name}: configured")
        else:
            info(f"{name}: not configured")

    # ClawHub safety check
    if (
        settings.clawhub_api_key.get_secret_value()
        and not settings.virustotal_api_key.get_secret_value()
        and settings.clawhub_auto_scan
    ):
        report.warn("ClawHub configured but VirusTotal key missing — skill install will be restricted")


def _check_launchd(report: DoctorReport) -> None:
    """Check macOS launchd service status."""
    if platform.system() != "Darwin":
        return

    header("Service (launchd)")

    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.fochs.bot.plist"
    if plist_path.is_file():
        report.ok(f"Plist found: {plist_path}")

        # Check if loaded
        try:
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "com.fochs.bot" in result.stdout:
                report.ok("Service is loaded in launchctl")
            else:
                report.warn("Plist exists but service is not loaded")
                info(f"Run: launchctl load {plist_path}")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            report.warn("Could not check launchctl status")
    else:
        info("No launchd plist found (optional)")
        info("Generate one with: fochs setup --generate-plist")


def _check_systemd(report: DoctorReport) -> None:
    """Check Linux systemd service status."""
    if platform.system() != "Linux":
        return

    header("Service (systemd)")

    unit_path = Path("/etc/systemd/system/fochs.service")
    if not unit_path.is_file():
        info("No systemd unit file at /etc/systemd/system/fochs.service")
        info("Install with: sudo cp deploy/fochs.service /etc/systemd/system/")
        return

    report.ok("Unit file installed")

    # Check enabled
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", "fochs"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() == "enabled":
            report.ok("Service is enabled (starts on boot)")
        else:
            report.warn(f"Service is {result.stdout.strip()} (not enabled)")
            info("Run: sudo systemctl enable fochs")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        report.warn("Could not check systemd enabled status")

    # Check active
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "fochs"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = result.stdout.strip()
        if status == "active":
            report.ok("Service is running")
        elif status == "inactive":
            report.warn("Service is not running")
            info("Run: sudo systemctl start fochs")
        else:
            report.err(f"Service status: {status}")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        report.warn("Could not check systemd active status")


def _check_disk_space(report: DoctorReport, settings: Settings) -> None:
    """Check available disk space in the data directory."""
    header("Disk Space")

    data_dir = Path(settings.data_dir)
    target = data_dir if data_dir.is_dir() else Path.cwd()

    try:
        usage = shutil.disk_usage(target)
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = (usage.used / usage.total) * 100

        report.ok(f"Disk: {free_gb:.1f} GB free of {total_gb:.1f} GB ({used_pct:.0f}% used)")

        if free_gb < 1.0:
            report.err("Less than 1 GB free — risk of data corruption")
        elif free_gb < 5.0:
            report.warn("Less than 5 GB free — consider freeing space")
    except Exception as e:
        report.warn(f"Could not check disk space: {e}")


def _check_port(report: DoctorReport, settings: Settings) -> None:
    """Check if the web dashboard port is available."""
    header("Network")

    host = settings.web_host
    port = settings.web_port

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            # Port is in use — could be Fochs itself or something else
            report.warn(f"Port {host}:{port} is already in use (may be Fochs running)")
        else:
            report.ok(f"Port {host}:{port} is available")
    except Exception as e:
        report.warn(f"Could not check port {host}:{port}: {e}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_doctor() -> None:
    """Run all health checks and print summary."""
    print()
    print(f"  {BOLD}\U0001f98a Fochs Doctor — Health Check{RESET}")
    print(f"  {DIM}Checking your Fochs installation...{RESET}")

    report = DoctorReport()

    # 1. System
    _check_system(report)

    # 2. Configuration (returns settings for subsequent checks)
    settings = _check_config(report)
    if not settings:
        # Can't continue without valid config
        _print_summary(report)
        return

    # 3. Directories
    _check_directories(report, settings)

    # 4. LLM connectivity
    try:
        await _check_llm(report, settings)
    except Exception as e:
        report.err(f"LLM check failed: {e}")

    # 5. Database
    try:
        await _check_database(report, settings)
    except Exception as e:
        report.err(f"Database check failed: {e}")

    # 6. Budget state
    _check_budget_state(report, settings)

    # 7. Optional integrations
    _check_optional_integrations(report, settings)

    # 8. launchd (macOS only)
    _check_launchd(report)

    # 9. systemd (Linux only)
    _check_systemd(report)

    # 10. Disk space
    _check_disk_space(report, settings)

    # 11. Port availability
    _check_port(report, settings)

    # Summary
    _print_summary(report)


def _print_summary(report: DoctorReport) -> None:
    """Print the final summary."""
    header("Summary")

    print(f"  {GREEN}Passed:{RESET}   {report.passed}")
    print(f"  {YELLOW}Warnings:{RESET} {report.warnings}")
    print(f"  {RED}Errors:{RESET}   {report.errors}")
    print()

    if report.errors == 0:
        if report.warnings == 0:
            print(f"  {GREEN}{BOLD}All checks passed! Fochs is ready to run.{RESET}")
        else:
            print(f"  {YELLOW}{BOLD}No errors, but {report.warnings} warning(s) to review.{RESET}")
        print(f"  Start with: {BOLD}uv run fochs{RESET}")
    else:
        print(f"  {RED}{BOLD}{report.errors} error(s) found. Please fix before running Fochs.{RESET}")
        print(f"  Run {BOLD}fochs setup{RESET} to reconfigure, or edit .env manually.")

    print()
