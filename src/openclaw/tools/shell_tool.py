"""Shell execute tool - run commands with security guard validation."""

from __future__ import annotations

import asyncio
import shlex
from typing import TYPE_CHECKING, Any

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.security.shell_guard import ShellGuard

logger = structlog.get_logger()

# Maximum output size before truncation
_MAX_OUTPUT = 50_000


class ShellExecuteTool(BaseTool):
    """Execute shell commands on the host machine.

    Respects the configured security profile (restricted/standard/unrestricted).
    All commands are validated before execution and audit-logged after.
    """

    name = "shell_execute"
    description = (
        "Fuehre einen Shell-Befehl auf der Maschine aus. "
        "Verfuegbarkeit haengt vom konfigurierten Sicherheitsprofil ab "
        "(restricted=nur lesen, standard=allgemein, unrestricted=alles)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Der auszufuehrende Shell-Befehl",
            },
            "working_dir": {
                "type": "string",
                "description": "Arbeitsverzeichnis (optional, default: erlaubtes Verzeichnis)",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in Sekunden (optional, default: 30, max: 300)",
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        guard: ShellGuard,
        default_timeout: int = 30,
        max_timeout: int = 300,
    ) -> None:
        self._guard = guard
        self._default_timeout = default_timeout
        self._max_timeout = max_timeout

    async def execute(self, **kwargs: Any) -> str:
        """Execute a shell command with security validation."""
        command: str = kwargs["command"]
        working_dir: str | None = kwargs.get("working_dir")
        timeout: int = min(kwargs.get("timeout", self._default_timeout), self._max_timeout)

        # --- Security validation ---
        error = self._guard.validate(command)
        if error:
            self._guard.audit_log(command, exit_code=-1, output_length=0, blocked=True, error=error)
            return f"BLOCKIERT: {error}"

        # Validate working directory if specified
        if working_dir:
            path_error = self._guard.validate_path(working_dir)
            if path_error:
                self._guard.audit_log(command, exit_code=-1, output_length=0, blocked=True, error=path_error)
                return f"BLOCKIERT: {path_error}"

        # --- Parse and execute ---
        try:
            parts = shlex.split(command)
        except ValueError as e:
            err = f"Befehl konnte nicht geparst werden: {e}"
            self._guard.audit_log(command, exit_code=-1, output_length=0, error=err)
            return err

        if not parts:
            return "Leerer Befehl."

        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            err = f"Befehl abgebrochen nach {timeout}s Timeout."
            self._guard.audit_log(command, exit_code=-1, output_length=0, error=err)
            return err
        except FileNotFoundError:
            err = f"Befehl nicht gefunden: {parts[0]}"
            self._guard.audit_log(command, exit_code=-1, output_length=0, error=err)
            return err
        except PermissionError:
            err = f"Keine Berechtigung: {parts[0]}"
            self._guard.audit_log(command, exit_code=-1, output_length=0, error=err)
            return err
        except OSError as e:
            err = f"Systemfehler: {e}"
            self._guard.audit_log(command, exit_code=-1, output_length=0, error=err)
            return err

        exit_code = proc.returncode or 0
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # Build result
        result_parts: list[str] = []
        if stdout:
            result_parts.append(stdout)
        if stderr:
            result_parts.append(f"[STDERR]\n{stderr}")
        result_parts.append(f"[Exit Code: {exit_code}]")
        result = "\n".join(result_parts)

        # Truncate if needed
        if len(result) > _MAX_OUTPUT:
            result = result[:_MAX_OUTPUT] + f"\n[Ausgabe gekuerzt bei {_MAX_OUTPUT} Zeichen]"

        # Audit log
        self._guard.audit_log(command, exit_code=exit_code, output_length=len(result))

        return result
