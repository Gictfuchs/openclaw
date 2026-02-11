"""Shell security guard: validates commands against configurable security profiles."""

from __future__ import annotations

import re
import shlex
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Absolute blocklist - blocked in ALL modes (even unrestricted)
# ---------------------------------------------------------------------------
_ABSOLUTE_BLOCKLIST: list[re.Pattern[str]] = [
    re.compile(r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?/\s*$"),  # rm -rf /
    re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/\s*$"),  # rm -r /
    re.compile(r"dd\s+.*if=/dev/(zero|random|urandom).*of=/dev/"),  # dd wipe disk
    re.compile(r"mkfs"),  # format filesystem
    re.compile(r">\s*/dev/sd[a-z]"),  # overwrite disk device
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\}"),  # fork bomb
    re.compile(r"chmod\s+(-R\s+)?0?777\s+/\s*$"),  # chmod 777 /
]

# ---------------------------------------------------------------------------
# Restricted mode: allowlist of read-only commands
# ---------------------------------------------------------------------------
_RESTRICTED_ALLOWLIST: set[str] = {
    # Filesystem info
    "ls",
    "ll",
    "dir",
    "cat",
    "head",
    "tail",
    "less",
    "wc",
    "file",
    "stat",
    "find",
    "locate",
    "which",
    "whereis",
    "realpath",
    "readlink",
    # System info
    "df",
    "du",
    "free",
    "top",
    "htop",
    "uptime",
    "uname",
    "hostname",
    "whoami",
    "id",
    "env",
    "printenv",
    "date",
    "cal",
    # Process info
    "ps",
    "pgrep",
    "lsof",
    # Network info
    "ip",
    "ifconfig",
    "ss",
    "netstat",
    "ping",
    "dig",
    "nslookup",
    "curl",
    # Package info
    "pip",
    "python",
    "pip3",
    "python3",
    # Git (read-only)
    "git",
    # Service info
    "systemctl",
    "journalctl",
    # Disk info
    "lsblk",
    "blkid",
    "mount",
}

# Git subcommands allowed in restricted mode
_RESTRICTED_GIT_SUBCOMMANDS: set[str] = {
    "status",
    "log",
    "diff",
    "branch",
    "remote",
    "show",
    "tag",
    "describe",
}

# Pip subcommands allowed in restricted mode
_RESTRICTED_PIP_SUBCOMMANDS: set[str] = {
    "list",
    "show",
    "freeze",
    "check",
}

# Systemctl subcommands allowed in restricted mode
_RESTRICTED_SYSTEMCTL_SUBCOMMANDS: set[str] = {
    "status",
    "is-active",
    "is-enabled",
    "list-units",
    "list-unit-files",
}

# ---------------------------------------------------------------------------
# Standard mode: blocklist of dangerous patterns
# ---------------------------------------------------------------------------
_STANDARD_BLOCKLIST: list[re.Pattern[str]] = [
    re.compile(r"sudo\s"),  # no sudo
    re.compile(r"\bsu\s"),  # no su
    re.compile(r"curl\s.*\|\s*(ba)?sh"),  # curl | bash
    re.compile(r"wget\s.*\|\s*(ba)?sh"),  # wget | bash
    re.compile(r"\beval\s"),  # eval
    re.compile(r"\bexec\s"),  # exec
    re.compile(r">\s*/etc/"),  # write to /etc
    re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/"),  # rm -r /anything at root
    re.compile(r"chmod\s+(-R\s+)?0?777\s"),  # chmod 777 anywhere
    re.compile(r"chown\s.*root"),  # chown to root
    re.compile(r"crontab\s+-r"),  # crontab -r (remove all)
    re.compile(r"shutdown|reboot|poweroff|halt"),  # system power control
    re.compile(r"iptables|nftables|ufw"),  # firewall modification
    re.compile(r"useradd|userdel|usermod|groupadd"),  # user management
]

# Sensitive file paths - blocked in all modes for file tools
SENSITIVE_PATHS: list[re.Pattern[str]] = [
    re.compile(r"/etc/shadow"),
    re.compile(r"/etc/passwd"),
    re.compile(r"/etc/sudoers"),
    re.compile(r".*\.ssh/"),
    re.compile(r".*\.gnupg/"),
    re.compile(r".*\.env$"),
    re.compile(r".*\.env\..*"),
    re.compile(r".*/\.git/config$"),
    re.compile(r".*/credentials"),
    re.compile(r".*/\.aws/"),
    re.compile(r".*/\.kube/"),
]


class ShellGuard:
    """Validates shell commands against security profiles.

    Profiles:
    - restricted: Read-only commands only (allowlist-based)
    - standard: General use with dangerous patterns blocked (blocklist-based)
    - unrestricted: Everything allowed except absolute blocklist
    """

    def __init__(
        self,
        mode: str = "restricted",
        allowed_dirs: list[str] | None = None,
    ) -> None:
        if mode not in ("restricted", "standard", "unrestricted"):
            msg = f"Invalid shell mode: {mode!r}. Must be restricted, standard, or unrestricted."
            raise ValueError(msg)
        self.mode = mode
        self.allowed_dirs = allowed_dirs or ["/tmp"]
        logger.info("shell_guard_initialized", mode=mode, allowed_dirs=self.allowed_dirs)

    def validate(self, command: str) -> str | None:
        """Validate a command against the current security profile.

        Returns None if the command is allowed, or an error message if blocked.
        """
        command = command.strip()
        if not command:
            return "Leerer Befehl."

        # Always check absolute blocklist
        for pattern in _ABSOLUTE_BLOCKLIST:
            if pattern.search(command):
                logger.warning("shell_guard_absolute_block", command=command)
                return "Befehl blockiert (Sicherheit): Dieser Befehl ist in allen Modi verboten."

        if self.mode == "restricted":
            return self._validate_restricted(command)
        elif self.mode == "standard":
            return self._validate_standard(command)
        # unrestricted: absolute blocklist already checked above
        return None

    def _validate_restricted(self, command: str) -> str | None:
        """Restricted mode: only allowlisted commands."""
        try:
            parts = shlex.split(command)
        except ValueError:
            return "Befehl konnte nicht geparst werden."

        if not parts:
            return "Leerer Befehl."

        base_cmd = parts[0].split("/")[-1]  # Handle full paths like /usr/bin/ls

        if base_cmd not in _RESTRICTED_ALLOWLIST:
            return (
                f"Befehl '{base_cmd}' ist im restricted-Modus nicht erlaubt. "
                f"Erlaubt: Nur lesende Befehle (ls, cat, df, ps, git status, ...)"
            )

        # Check subcommands for tools with mixed capabilities
        if base_cmd == "git" and len(parts) > 1:
            subcmd = parts[1]
            if subcmd not in _RESTRICTED_GIT_SUBCOMMANDS:
                return f"git {subcmd} ist im restricted-Modus nicht erlaubt. Erlaubt: {', '.join(sorted(_RESTRICTED_GIT_SUBCOMMANDS))}"

        if base_cmd in ("pip", "pip3") and len(parts) > 1:
            subcmd = parts[1]
            if subcmd not in _RESTRICTED_PIP_SUBCOMMANDS:
                return f"pip {subcmd} ist im restricted-Modus nicht erlaubt. Erlaubt: {', '.join(sorted(_RESTRICTED_PIP_SUBCOMMANDS))}"

        if base_cmd == "systemctl" and len(parts) > 1:
            subcmd = parts[1]
            if subcmd not in _RESTRICTED_SYSTEMCTL_SUBCOMMANDS:
                return f"systemctl {subcmd} ist im restricted-Modus nicht erlaubt. Erlaubt: {', '.join(sorted(_RESTRICTED_SYSTEMCTL_SUBCOMMANDS))}"

        # Block python -c / python -m with arbitrary code in restricted
        if base_cmd in ("python", "python3") and len(parts) > 1 and parts[1] in ("-c", "-m"):
            return "python -c/-m ist im restricted-Modus nicht erlaubt."

        return None

    def _validate_standard(self, command: str) -> str | None:
        """Standard mode: block dangerous patterns."""
        for pattern in _STANDARD_BLOCKLIST:
            if pattern.search(command):
                logger.warning("shell_guard_standard_block", command=command, pattern=pattern.pattern)
                return "Befehl blockiert im standard-Modus: Entspricht Sicherheitsregel."

        # Check working directory is within allowed dirs
        # (actual enforcement happens in ShellExecuteTool)
        return None

    def validate_path(self, path: str) -> str | None:
        """Validate a file path against allowed directories and sensitive paths.

        Returns None if allowed, or an error message if blocked.
        """
        from pathlib import Path

        resolved = str(Path(path).resolve())

        # Check sensitive paths (blocked in ALL modes)
        for pattern in SENSITIVE_PATHS:
            if pattern.search(resolved):
                return f"Zugriff auf sensiblen Pfad verweigert: {path}"

        # In restricted and standard mode, check allowed directories
        if self.mode != "unrestricted":
            in_allowed = any(resolved.startswith(str(Path(d).resolve())) for d in self.allowed_dirs)
            if not in_allowed:
                return f"Pfad '{path}' liegt ausserhalb der erlaubten Verzeichnisse: {', '.join(self.allowed_dirs)}"

        return None

    def audit_log(
        self,
        command: str,
        exit_code: int,
        output_length: int,
        *,
        blocked: bool = False,
        error: str | None = None,
    ) -> None:
        """Log a shell command execution for audit purposes."""
        logger.info(
            "shell_audit",
            command=command,
            exit_code=exit_code,
            output_length=output_length,
            mode=self.mode,
            blocked=blocked,
            error=error,
        )

    def get_status(self) -> dict[str, Any]:
        """Return current guard status."""
        return {
            "mode": self.mode,
            "allowed_dirs": self.allowed_dirs,
        }
