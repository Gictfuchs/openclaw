"""Self-update tool - git pull + pip install + restart."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.security.shell_guard import ShellGuard

logger = structlog.get_logger()


class SelfUpdateTool(BaseTool):
    """Update Fochs to the latest version.

    Performs: git pull → pip install -e . → restart.
    Always requires confirmation (ask-gated) even at autonomy_level=full.
    Only available in standard or unrestricted mode.
    """

    name = "self_update"
    description = (
        "Update Fochs auf die neueste Version (git pull + install + restart). "
        "ACHTUNG: Startet den Agenten neu. Nur mit Bestaetigung."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "confirm": {
                "type": "boolean",
                "description": "Muss true sein um das Update durchzufuehren",
            },
            "show_diff_only": {
                "type": "boolean",
                "description": "Nur git diff anzeigen ohne Update (default: false)",
            },
        },
        "required": ["confirm"],
    }

    def __init__(
        self,
        guard: ShellGuard,
        project_dir: str = "/opt/fochs",
        restart_command: str = "systemctl restart fochs",
    ) -> None:
        self._guard = guard
        self._project_dir = project_dir
        self._restart_cmd = restart_command

    async def execute(self, **kwargs: Any) -> str:
        """Execute self-update sequence."""
        confirm: bool = kwargs.get("confirm", False)
        show_diff_only: bool = kwargs.get("show_diff_only", False)

        # Security: only standard or unrestricted
        if self._guard.mode == "restricted":
            return "BLOCKIERT: Self-Update ist im restricted-Modus nicht erlaubt."

        project = Path(self._project_dir)
        if not project.is_dir():
            return f"Projekt-Verzeichnis nicht gefunden: {self._project_dir}"

        if not (project / ".git").is_dir():
            return f"Kein Git-Repository: {self._project_dir}"

        # Show diff only mode
        if show_diff_only:
            return await self._show_diff()

        # Require explicit confirmation
        if not confirm:
            return (
                "Self-Update erfordert explizite Bestaetigung. "
                "Setze confirm=true um fortzufahren. "
                "Nutze show_diff_only=true um zuerst die Aenderungen zu sehen."
            )

        # Execute update sequence
        steps: list[str] = []

        # Step 1: git fetch + check for updates
        fetch_result = await self._run(["git", "-C", self._project_dir, "fetch", "origin"])
        if fetch_result.returncode != 0:
            return f"git fetch fehlgeschlagen:\n{fetch_result.stderr}"

        # Check if there are updates
        diff_result = await self._run(["git", "-C", self._project_dir, "log", "HEAD..origin/main", "--oneline"])
        if not diff_result.stdout.strip():
            return "Bereits auf dem neuesten Stand. Kein Update noetig."

        steps.append(f"Neue Commits:\n{diff_result.stdout.strip()}")

        # Step 2: git pull
        pull_result = await self._run(["git", "-C", self._project_dir, "pull", "origin", "main"])
        if pull_result.returncode != 0:
            return f"git pull fehlgeschlagen:\n{pull_result.stderr}"
        steps.append("git pull: OK")

        # Step 3: pip install
        install_result = await self._run(
            ["pip", "install", "-e", self._project_dir],
            timeout=120,
        )
        if install_result.returncode != 0:
            return f"pip install fehlgeschlagen:\n{install_result.stderr}"
        steps.append("pip install: OK")

        # Step 4: Restart (this will kill the current process)
        steps.append(f"Neustart wird ausgefuehrt: {self._restart_cmd}")
        logger.info("self_update_restart", command=self._restart_cmd)

        result = "\n".join(steps)

        # Fire and forget restart
        try:
            parts = self._restart_cmd.split()
            await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception as e:
            result += f"\nWARNUNG: Restart fehlgeschlagen: {e}"

        return result

    async def _show_diff(self) -> str:
        """Show what would change on update."""
        fetch = await self._run(["git", "-C", self._project_dir, "fetch", "origin"])
        if fetch.returncode != 0:
            return f"git fetch fehlgeschlagen:\n{fetch.stderr}"

        log = await self._run(
            ["git", "-C", self._project_dir, "log", "HEAD..origin/main", "--oneline", "--no-decorate"]
        )
        diff = await self._run(["git", "-C", self._project_dir, "diff", "HEAD..origin/main", "--stat"])

        if not log.stdout.strip():
            return "Keine neuen Aenderungen auf origin/main."

        return f"Ausstehende Commits:\n{log.stdout}\nDatei-Aenderungen:\n{diff.stdout}"

    async def _run(
        self,
        cmd: list[str],
        timeout: int = 30,
    ) -> asyncio.subprocess.Process:
        """Run a subprocess and return the completed process."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            # Create a simple result object
            proc.stdout_text = ""  # type: ignore[attr-defined]
            proc.stderr_text = f"Timeout nach {timeout}s"  # type: ignore[attr-defined]
            return proc

        # Attach decoded text to proc for easy access
        proc.stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""  # type: ignore[attr-defined]
        proc.stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""  # type: ignore[attr-defined]

        # Make stdout/stderr accessible as .stdout/.stderr strings
        proc.stdout = proc.stdout_text  # type: ignore[assignment]
        proc.stderr = proc.stderr_text  # type: ignore[assignment]
        return proc
