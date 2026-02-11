"""Bootstrap command — ``fochs preflight``.

Runs the complete sequence from fresh clone to ready-to-run:
  1. Check prerequisites (Python, uv, git)
  2. Run ``uv sync``
  3. Copy ``.env.example`` if no ``.env`` exists
  4. Create data/plugins directories
  5. Run ``fochs setup`` (interactive or ``--non-interactive``)
  6. Run ``fochs doctor``
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from openclaw.cli._helpers import find_project_dir, run_uv_sync
from openclaw.cli.output import BOLD, RESET, err, header, info, ok, warn

# ---------------------------------------------------------------------------
# Preflight steps
# ---------------------------------------------------------------------------


def _check_prereqs() -> bool:
    """Verify Python 3.12+, uv, and git are available."""
    header("Step 1/4: Prerequisites")

    all_ok = True
    v = sys.version_info
    if v >= (3, 12):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        err(f"Python {v.major}.{v.minor} — need 3.12+")
        all_ok = False

    for cmd, label in [("uv", "uv package manager"), ("git", "Git")]:
        if shutil.which(cmd):
            ok(f"{label} found")
        else:
            err(f"{label} not found")
            all_ok = False

    return all_ok


def _ensure_env_file(project_dir: Path) -> None:
    """Copy ``.env.example`` to ``.env`` if ``.env`` does not exist."""
    env_path = project_dir / ".env"
    example = project_dir / ".env.example"
    if not env_path.is_file() and example.is_file():
        shutil.copy2(example, env_path)
        ok(f"Created .env from {example.name}")
    elif env_path.is_file():
        ok(".env already exists")
    else:
        warn("No .env or .env.example found — setup wizard will create one")


def _ensure_dirs(project_dir: Path) -> None:
    """Create data, plugins, logs, and chroma directories.

    Reads FOCHS_DATA_DIR / FOCHS_PLUGINS_DIR from ``.env`` when available,
    otherwise falls back to sensible defaults.
    """
    # Try to read config-aware paths from .env
    data_dir = project_dir / "data"
    plugins_dir = project_dir / "plugins"

    env_path = project_dir / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FOCHS_DATA_DIR="):
                raw = line.split("=", 1)[1].strip().strip("'\"")
                candidate = Path(raw)
                data_dir = candidate if candidate.is_absolute() else project_dir / candidate
            elif line.startswith("FOCHS_PLUGINS_DIR="):
                raw = line.split("=", 1)[1].strip().strip("'\"")
                candidate = Path(raw)
                plugins_dir = candidate if candidate.is_absolute() else project_dir / candidate

    dirs = [
        data_dir,
        data_dir / "chroma",
        data_dir / "logs",
        plugins_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    ok(f"Directories ready ({len(dirs)} dirs)")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_preflight(*, non_interactive: bool = False) -> None:
    """Run the full preflight bootstrap sequence."""
    print()
    print(f"  {BOLD}\U0001f98a Fochs Preflight — Bootstrap{RESET}")
    print()

    project_dir = find_project_dir()

    if not (project_dir / "pyproject.toml").is_file():
        err("Not in a Fochs project (no pyproject.toml found)")
        sys.exit(1)

    ok(f"Project: {project_dir}")

    # 1. Prerequisites
    if not _check_prereqs():
        err("Fix prerequisites before continuing")
        sys.exit(1)

    # 2. uv sync
    header("Step 2/4: Install Dependencies")
    if not run_uv_sync(project_dir):
        err("Dependency installation failed")
        sys.exit(1)

    # 3. .env file + directories
    header("Step 3/4: Environment & Directories")
    _ensure_env_file(project_dir)
    _ensure_dirs(project_dir)

    # 4. Setup wizard
    header("Step 4/4: Configuration")
    from openclaw.cli.setup import run_setup

    run_setup(non_interactive=non_interactive, generate_plist=False)

    # 5. Health check (best-effort, don't fail on this)
    info("Running health check...")
    try:
        import asyncio

        from openclaw.cli.doctor import run_doctor

        asyncio.run(run_doctor())
    except (ImportError, OSError) as e:
        warn(f"Health check encountered an error: {e}")
        info("Run 'fochs doctor' manually to diagnose")

    print()
    ok(f"Preflight complete! Start with: {BOLD}uv run fochs{RESET}")
    print()
