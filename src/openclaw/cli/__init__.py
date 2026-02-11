"""Fochs CLI — interactive setup wizard and diagnostic tools.

Entry point: ``fochs`` (or ``python -m openclaw``)

Subcommands:
    fochs          — Start the bot (default)
    fochs setup    — Interactive first-run configuration wizard
    fochs doctor   — Health-check / diagnostic report
    fochs preflight — Full bootstrap: prereqs → install → setup → doctor
    fochs update   — Update Fochs (git pull + uv sync + restart)
"""

from __future__ import annotations

import argparse
import asyncio


def main() -> None:
    """Main CLI entry point dispatching to subcommands."""
    parser = argparse.ArgumentParser(
        prog="fochs",
        description="Fochs — An autonomous AI agent powered by OpenClaw",
    )
    sub = parser.add_subparsers(dest="command")

    # --- fochs setup ---
    setup_parser = sub.add_parser("setup", help="Interactive first-run configuration wizard")
    setup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Validate existing .env without prompts (for CI/CD)",
    )
    setup_parser.add_argument(
        "--generate-plist",
        action="store_true",
        help="Generate a macOS launchd plist for auto-start",
    )

    # --- fochs doctor ---
    sub.add_parser("doctor", help="Run health checks and diagnostics")

    # --- fochs preflight ---
    preflight_parser = sub.add_parser(
        "preflight",
        help="Full bootstrap: prereqs → install → setup → doctor",
    )
    preflight_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without prompts (for CI/CD)",
    )

    # --- fochs update ---
    update_parser = sub.add_parser(
        "update",
        help="Update Fochs (git pull + uv sync + restart)",
    )
    update_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without applying",
    )
    update_parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Skip automatic service restart",
    )

    args = parser.parse_args()

    if args.command == "setup":
        from openclaw.cli.setup import run_setup

        run_setup(non_interactive=args.non_interactive, generate_plist=args.generate_plist)
    elif args.command == "doctor":
        from openclaw.cli.doctor import run_doctor

        asyncio.run(run_doctor())
    elif args.command == "preflight":
        from openclaw.cli.preflight import run_preflight

        run_preflight(non_interactive=args.non_interactive)
    elif args.command == "update":
        from openclaw.cli.update import run_update

        run_update(dry_run=args.dry_run, restart=not args.no_restart)
    else:
        # Default: start the bot
        from openclaw.app import FochsApp

        app = FochsApp()
        asyncio.run(app.start())


if __name__ == "__main__":
    main()
