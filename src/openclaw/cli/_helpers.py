"""Shared CLI helpers — used across setup, preflight, update, doctor.

Avoids duplication of project-root discovery, ``uv sync`` execution,
and timeout constants.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from openclaw.cli.output import err, info, ok, warn

# ---------------------------------------------------------------------------
# Timeout constants (seconds) — tune for slow networks via env if needed
# ---------------------------------------------------------------------------
TIMEOUT_UV_SYNC: int = 300
TIMEOUT_GIT_FETCH: int = 30
TIMEOUT_GIT_PULL: int = 120
TIMEOUT_SERVICE_CMD: int = 15
TIMEOUT_STATUS_CMD: int = 5


# ---------------------------------------------------------------------------
# Project root discovery
# ---------------------------------------------------------------------------


def find_project_dir() -> Path:
    """Locate the project root (directory containing ``pyproject.toml``).

    Walks up from cwd to find the first parent that contains a
    ``pyproject.toml``.  Returns cwd as fallback.
    """
    project_dir = Path.cwd()
    if (project_dir / "pyproject.toml").is_file():
        return project_dir
    for parent in project_dir.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return project_dir


# ---------------------------------------------------------------------------
# Dependency installation
# ---------------------------------------------------------------------------


def run_uv_sync(project_dir: Path, *, quiet: bool = False) -> bool:
    """Run ``uv sync`` to install/update dependencies.

    Returns ``True`` on success, ``False`` on failure or timeout.
    """
    if not shutil.which("uv"):
        warn("uv not found — skipping dependency install")
        return False

    if not quiet:
        info("Running uv sync...")
    try:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_UV_SYNC,
        )
        if result.returncode == 0:
            ok("Dependencies installed")
            return True
        err(f"uv sync failed: {result.stderr[:300]}")
        return False
    except FileNotFoundError:
        err("uv binary not found")
        return False
    except subprocess.TimeoutExpired:
        err(f"uv sync timed out ({TIMEOUT_UV_SYNC}s)")
        return False
