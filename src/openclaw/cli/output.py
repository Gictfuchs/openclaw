"""Shared CLI output helpers — ANSI colors and status formatting.

Used by all CLI subcommands (setup, doctor, preflight, update) to
provide consistent, colored terminal output.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# ANSI helpers (gracefully degrade when stdout is not a TTY)
# ---------------------------------------------------------------------------
SUPPORTS_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

GREEN = "\033[92m" if SUPPORTS_COLOR else ""
YELLOW = "\033[93m" if SUPPORTS_COLOR else ""
RED = "\033[91m" if SUPPORTS_COLOR else ""
CYAN = "\033[96m" if SUPPORTS_COLOR else ""
BOLD = "\033[1m" if SUPPORTS_COLOR else ""
DIM = "\033[2m" if SUPPORTS_COLOR else ""
RESET = "\033[0m" if SUPPORTS_COLOR else ""


def ok(msg: str) -> None:
    """Print a success message with green checkmark."""
    print(f"  {GREEN}\u2713{RESET} {msg}")


def warn(msg: str) -> None:
    """Print a warning message with yellow symbol."""
    print(f"  {YELLOW}\u26a0{RESET} {msg}")


def err(msg: str) -> None:
    """Print an error message with red cross."""
    print(f"  {RED}\u2717{RESET} {msg}")


def info(msg: str) -> None:
    """Print an informational message with cyan symbol."""
    print(f"  {CYAN}\u2139{RESET} {msg}")


def header(title: str) -> None:
    """Print a section header with horizontal rules."""
    width = 60
    print()
    print(f"  {BOLD}{'\u2500' * width}{RESET}")
    print(f"  {BOLD}{title}{RESET}")
    print(f"  {BOLD}{'\u2500' * width}{RESET}")
    print()
