"""CLI update command — ``fochs update``.

Performs: ``git pull`` → ``uv sync`` → optional service restart.
Handles both macOS (launchctl) and Linux (systemctl).
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from openclaw.cli._helpers import (
    TIMEOUT_GIT_FETCH,
    TIMEOUT_GIT_PULL,
    TIMEOUT_SERVICE_CMD,
    TIMEOUT_STATUS_CMD,
    find_project_dir,
    run_uv_sync,
)
from openclaw.cli.output import BOLD, RESET, err, header, info, ok, warn

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _detect_service_manager() -> str | None:
    """Detect whether the Fochs service is managed by systemd or launchd."""
    system = platform.system()
    if system == "Linux":
        try:
            result = _run(["systemctl", "is-enabled", "fochs"], timeout=TIMEOUT_STATUS_CMD)
            if result.returncode == 0:
                return "systemd"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    elif system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.fochs.bot.plist"
        if plist.is_file():
            return "launchd"
    return None


def _restart_service(manager: str) -> bool:
    """Restart the Fochs service. Returns True on success."""
    try:
        if manager == "systemd":
            result = _run(["sudo", "systemctl", "restart", "fochs"], timeout=TIMEOUT_SERVICE_CMD)
            return result.returncode == 0
        if manager == "launchd":
            label = "com.fochs.bot"
            _run(["launchctl", "stop", label], timeout=TIMEOUT_STATUS_CMD)
            result = _run(["launchctl", "start", label], timeout=TIMEOUT_STATUS_CMD)
            return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_update(*, dry_run: bool = False, restart: bool = True) -> None:
    """Run the CLI update sequence."""
    print()
    print(f"  {BOLD}\U0001f98a Fochs Update{RESET}")
    print()

    project_dir = find_project_dir()

    if not (project_dir / ".git").is_dir():
        err("Not a git repository — cannot update")
        sys.exit(1)

    # Step 1: git fetch + check for updates
    header("Checking for updates")
    try:
        fetch = _run(["git", "-C", str(project_dir), "fetch", "origin"], timeout=TIMEOUT_GIT_FETCH)
    except subprocess.TimeoutExpired:
        err("git fetch timed out")
        sys.exit(1)

    if fetch.returncode != 0:
        err(f"git fetch failed: {fetch.stderr[:200]}")
        sys.exit(1)

    log = _run(["git", "-C", str(project_dir), "log", "HEAD..origin/main", "--oneline"])
    if not log.stdout.strip():
        ok("Already up to date")
        return

    info("Available updates:")
    for line in log.stdout.strip().splitlines()[:20]:
        print(f"    {line}")

    if dry_run:
        print()
        info("Dry run — not applying changes")
        diff_stat = _run(["git", "-C", str(project_dir), "diff", "HEAD..origin/main", "--stat"])
        if diff_stat.stdout.strip():
            print()
            for line in diff_stat.stdout.strip().splitlines()[-5:]:
                print(f"    {line}")
        return

    # Step 2: Check for local changes
    status = _run(["git", "-C", str(project_dir), "status", "--porcelain"])
    if status.stdout.strip():
        warn("Working directory has uncommitted changes")
        info("Stash or commit your changes before updating")
        sys.exit(1)

    # Step 3: git pull
    header("Pulling updates")
    try:
        pull = _run(["git", "-C", str(project_dir), "pull", "origin", "main"], timeout=TIMEOUT_GIT_PULL)
    except subprocess.TimeoutExpired:
        err("git pull timed out")
        sys.exit(1)

    if pull.returncode != 0:
        err(f"git pull failed: {pull.stderr[:200]}")
        sys.exit(1)
    ok("Code updated")

    # Step 4: uv sync
    header("Installing dependencies")
    run_uv_sync(project_dir)

    # Step 5: Optional service restart
    if restart:
        manager = _detect_service_manager()
        if manager:
            header("Restarting service")
            info(f"Detected service manager: {manager}")
            if _restart_service(manager):
                ok(f"Service restarted via {manager}")
            else:
                warn(f"Could not restart service via {manager}")
                info("Restart manually to apply the update")
        else:
            info("No service manager detected — restart manually if needed")

    print()
    ok("Update complete")
    print()
