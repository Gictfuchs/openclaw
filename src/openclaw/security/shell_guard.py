"""Shell security guard: validates commands against configurable security profiles."""

from __future__ import annotations

import re
import shlex
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Absolute blocklist - blocked in ALL modes (even unrestricted)
# These patterns catch catastrophic commands that should NEVER execute.
# ---------------------------------------------------------------------------
_ABSOLUTE_BLOCKLIST: list[re.Pattern[str]] = [
    # rm -rf / variants (with or without trailing slash, wildcards, globbing)
    re.compile(r"rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)*(/\s*$|/\*|~\s*$|\$HOME\b|--no-preserve-root)"),
    # dd wipe disk (any if=/dev/... of=/dev/... combination)
    re.compile(r"dd\s+.*if=/dev/(zero|random|urandom).*of=/dev/"),
    re.compile(r"dd\s+.*of=/dev/[snv]d[a-z]"),  # dd of=/dev/sda regardless of source
    # Format filesystem
    re.compile(r"\bmkfs\b"),
    # Overwrite disk devices (including nvme)
    re.compile(r">\s*/dev/(sd[a-z]|nvme|vd[a-z]|xvd[a-z])"),
    # Fork bombs — multiple common variants
    re.compile(r":\(\)\s*\{.*:\|.*\}"),  # :(){ :|:& }
    re.compile(r"\.\(\)\s*\{.*\.\|.*\}"),  # .() variant
    re.compile(r"bomb\(\)\s*\{"),  # function-named fork bombs
    # chmod 777 / (root or home)
    re.compile(r"chmod\s+(-[a-zA-Z]*\s+)*0?777\s+(/\s*$|/\*|~\s*$|\$HOME\b)"),
    # Wipe partition table
    re.compile(r"wipefs\s+(-[a-zA-Z]*\s+)*/dev/"),
    # shred system partitions
    re.compile(r"shred\s+.*(/dev/[snv]d[a-z]|/dev/nvme)"),
]

# ---------------------------------------------------------------------------
# Restricted mode: allowlist of read-only commands
# ---------------------------------------------------------------------------
_RESTRICTED_ALLOWLIST: set[str] = {
    # Filesystem info (read-only)
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
    "find",  # Subcommand-checked: -exec, -delete blocked below
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
    # Network info (read-only only)
    "ip",
    "ifconfig",
    "ss",
    "netstat",
    "ping",
    "dig",
    "nslookup",
    # NOTE: curl removed from restricted - can POST/upload data
    # NOTE: mount removed from restricted - can mount filesystems
    # Package info
    "pip",  # Subcommand-checked below
    "python",  # Subcommand-checked below
    "pip3",
    "python3",
    # Git (read-only, subcommand-checked)
    "git",
    # Service info (subcommand-checked)
    "systemctl",
    "journalctl",  # Subcommand-checked below
    # Disk info
    "lsblk",
    "blkid",
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
    # Privilege escalation
    re.compile(r"\bsudo\s"),  # no sudo
    re.compile(r"\bsu\s"),  # no su
    re.compile(r"\bdoas\s"),  # no doas (sudo alternative)
    # Remote code execution via pipe
    re.compile(r"curl\s.*\|\s*(ba)?sh"),  # curl | bash
    re.compile(r"wget\s.*\|\s*(ba)?sh"),  # wget | bash
    re.compile(r"curl\s.*\|\s*python"),  # curl | python
    re.compile(r"wget\s.*\|\s*python"),  # wget | python
    # Code injection
    re.compile(r"\beval\s"),  # eval
    re.compile(r"\bexec\s"),  # exec
    re.compile(r"\bpython3?\s+-c\s"),  # python -c (arbitrary code)
    # System file modification
    re.compile(r">\s*/etc/"),  # write to /etc
    re.compile(r"\btee\s+/etc/"),  # tee to /etc
    # Recursive delete at root
    re.compile(r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)*(/|~|\$HOME)"),
    # Dangerous permissions
    re.compile(r"chmod\s+(-[a-zA-Z]*\s+)*0?777\s"),  # chmod 777 anywhere
    re.compile(r"chown\s.*root"),  # chown to root
    # Cron/scheduler manipulation
    re.compile(r"crontab\s+-[re]"),  # crontab -r (remove), -e (edit)
    # System power control
    re.compile(r"\b(shutdown|reboot|poweroff|halt|init\s+[06])\b"),
    # Firewall modification
    re.compile(r"\b(iptables|nftables|ufw|firewall-cmd)\b"),
    # User management
    re.compile(r"\b(useradd|userdel|usermod|groupadd|groupdel|groupmod)\b"),
    # Network tools that can exfiltrate or backdoor
    re.compile(r"\b(nc|ncat|netcat|socat)\s"),  # netcat variants
    re.compile(r"\bnmap\s"),  # port scanning
    # Kernel / module manipulation
    re.compile(r"\b(insmod|rmmod|modprobe)\s"),
    re.compile(r"\bsysctl\s+-w\s"),  # sysctl write
]

# Sensitive file paths - blocked in all modes for file tools
SENSITIVE_PATHS: list[re.Pattern[str]] = [
    # System auth files
    re.compile(r"/etc/shadow"),
    re.compile(r"/etc/passwd"),
    re.compile(r"/etc/sudoers"),
    re.compile(r"/etc/gshadow"),
    # SSH/GPG keys
    re.compile(r".*\.ssh/"),
    re.compile(r".*\.gnupg/"),
    # Private keys and certificates
    re.compile(r".*\.pem$"),
    re.compile(r".*\.key$"),
    re.compile(r".*\.p12$"),
    re.compile(r".*\.pfx$"),
    re.compile(r".*_rsa$"),
    re.compile(r".*_ed25519$"),
    re.compile(r".*_ecdsa$"),
    re.compile(r".*_dsa$"),
    # Environment files / secrets
    re.compile(r".*\.env$"),
    re.compile(r".*\.env\..*"),
    re.compile(r".*\.netrc$"),
    re.compile(r".*\.npmrc$"),
    re.compile(r".*\.pypirc$"),
    # Git credentials
    re.compile(r".*/\.git/config$"),
    re.compile(r".*/\.gitconfig$"),
    re.compile(r".*/credentials"),
    re.compile(r".*\.git-credentials$"),
    # Cloud provider configs
    re.compile(r".*/\.aws/"),
    re.compile(r".*/\.kube/"),
    re.compile(r".*/\.gcloud/"),
    re.compile(r".*/\.azure/"),
    re.compile(r".*/\.docker/config\.json$"),
    # Token/secret files
    re.compile(r".*token.*\.json$", re.IGNORECASE),
    re.compile(r".*secret.*\.json$", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
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

        # Block find with -exec, -execdir, -delete (can execute arbitrary commands)
        if base_cmd == "find":
            dangerous_find_args = {"-exec", "-execdir", "-delete", "-fls", "-ok", "-okdir"}
            for part in parts[1:]:
                if part in dangerous_find_args:
                    return f"find {part} ist im restricted-Modus nicht erlaubt (Code-Ausfuehrung/Loeschen)."

        # Block journalctl write operations
        if base_cmd == "journalctl":
            dangerous_journal_prefixes = ("--vacuum-size", "--vacuum-time", "--vacuum-files", "--rotate", "--flush")
            for part in parts[1:]:
                # Check both --flag and --flag=value forms
                if part in dangerous_journal_prefixes or any(
                    part.startswith(f"{p}=") for p in dangerous_journal_prefixes
                ):
                    flag = part.split("=")[0]
                    return f"journalctl {flag} ist im restricted-Modus nicht erlaubt."

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
