"""File system tools - read and write files with security validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.security.shell_guard import ShellGuard

logger = structlog.get_logger()

# Maximum file size for reading (100 KB)
_MAX_READ_SIZE = 100_000


class FileReadTool(BaseTool):
    """Read files and list directories.

    Respects path restrictions and sensitive file blocklist.
    Available in all security modes.
    """

    name = "file_read"
    description = (
        "Lese eine Datei oder liste ein Verzeichnis auf. Pfad muss innerhalb der erlaubten Verzeichnisse liegen."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Dateipfad oder Verzeichnispfad",
            },
        },
        "required": ["path"],
    }

    def __init__(self, guard: ShellGuard) -> None:
        self._guard = guard

    async def execute(self, **kwargs: Any) -> str:
        """Read a file or list a directory."""
        path_str: str = kwargs["path"]

        # Security: validate path
        error = self._guard.validate_path(path_str)
        if error:
            logger.warning("file_read_blocked", path=path_str, error=error)
            return f"BLOCKIERT: {error}"

        path = Path(path_str).resolve()

        if not path.exists():
            return f"Pfad existiert nicht: {path}"

        # Directory listing
        if path.is_dir():
            try:
                entries: list[str] = []
                for entry in sorted(path.iterdir()):
                    suffix = "/" if entry.is_dir() else ""
                    size = ""
                    if entry.is_file():
                        try:
                            size = f"  ({_human_size(entry.stat().st_size)})"
                        except OSError:
                            size = ""
                    entries.append(f"  {entry.name}{suffix}{size}")
                if not entries:
                    return f"Verzeichnis ist leer: {path}"
                return f"Inhalt von {path}:\n" + "\n".join(entries)
            except PermissionError:
                return f"Keine Berechtigung: {path}"

        # File reading
        if not path.is_file():
            return f"Kein regulaerer Pfad: {path}"

        try:
            file_size = path.stat().st_size
        except OSError as e:
            return f"Fehler beim Lesen: {e}"

        if file_size > _MAX_READ_SIZE:
            # Read only the first chunk
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:_MAX_READ_SIZE]
                return (
                    f"[Datei {_human_size(file_size)}, nur erste {_human_size(_MAX_READ_SIZE)} angezeigt]\n"
                    f"{content}\n[... gekuerzt]"
                )
            except (OSError, UnicodeDecodeError) as e:
                return f"Fehler beim Lesen: {e}"

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return content if content else "(Datei ist leer)"
        except (OSError, UnicodeDecodeError) as e:
            return f"Fehler beim Lesen: {e}"


class FileWriteTool(BaseTool):
    """Write or create files.

    Only available in standard or unrestricted mode.
    Respects path restrictions and sensitive file blocklist.
    """

    name = "file_write"
    description = (
        "Schreibe Inhalt in eine Datei (erstellt sie bei Bedarf). Nur im standard- oder unrestricted-Modus verfuegbar."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Zieldateipfad",
            },
            "content": {
                "type": "string",
                "description": "Dateiinhalt",
            },
            "append": {
                "type": "boolean",
                "description": "An Datei anhaengen statt ueberschreiben (default: false)",
            },
            "make_executable": {
                "type": "boolean",
                "description": "Datei ausfuehrbar machen (default: false)",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, guard: ShellGuard) -> None:
        self._guard = guard

    async def execute(self, **kwargs: Any) -> str:
        """Write content to a file."""
        path_str: str = kwargs["path"]
        content: str = kwargs["content"]
        append: bool = kwargs.get("append", False)
        make_executable: bool = kwargs.get("make_executable", False)

        # Security: only standard or unrestricted
        if self._guard.mode == "restricted":
            return "BLOCKIERT: Datei-Schreiben ist im restricted-Modus nicht erlaubt."

        # Security: validate path
        error = self._guard.validate_path(path_str)
        if error:
            logger.warning("file_write_blocked", path=path_str, error=error)
            return f"BLOCKIERT: {error}"

        path = Path(path_str).resolve()

        # Create parent directories if needed
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"Verzeichnis konnte nicht erstellt werden: {e}"

        # Write file
        mode = "a" if append else "w"
        action = "angehaengt" if append else "geschrieben"
        try:
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return f"Fehler beim Schreiben: {e}"

        # Make executable if requested
        if make_executable:
            try:
                os.chmod(path, 0o755)
            except OSError as e:
                return f"Datei geschrieben, aber chmod fehlgeschlagen: {e}"

        size = path.stat().st_size
        logger.info("file_written", path=str(path), size=size, mode=mode)
        return f"Datei {action}: {path} ({_human_size(size)})"


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}" if unit == "B" else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"
