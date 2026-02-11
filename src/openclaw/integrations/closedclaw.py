"""ClosedClaw Credential Vault - encrypted credential storage.

Provides a local AES-256-GCM encrypted vault so that API keys and secrets
never pass through the LLM context.  Only credential *names* and metadata
are exposed to the agent; raw values stay inside the vault and are resolved
internally by other integration clients.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = structlog.get_logger()

_NONCE_BYTES = 12  # 96-bit nonce for AES-GCM
_KEY_BYTES = 32  # 256-bit key


@dataclass
class CredentialRef:
    """A reference to a stored credential — never contains the raw value."""

    name: str
    backend: str = "vault-file"
    description: str = ""
    created_at: str = ""


@dataclass
class VaultStatus:
    """Current vault status."""

    backend: str
    locked: bool
    credential_count: int
    vault_path: str = ""


@dataclass(repr=False)
class _VaultData:
    """Internal vault file structure."""

    version: int = 1
    credentials: dict[str, dict[str, Any]] = field(default_factory=dict)


class ClosedClawClient:
    """Client for the ClosedClaw encrypted credential vault.

    The vault-file backend stores credentials encrypted with AES-256-GCM.
    The encryption key is derived from a master key stored separately.

    Security invariants:
    - ``resolve()`` is internal-only — never exposed as an agent tool
    - Tool-facing methods return only names/metadata, never raw values
    - Vault file is atomically written to prevent corruption
    """

    def __init__(
        self,
        vault_path: str,
        backend: str = "vault-file",
        unlock_timeout: int = 300,
    ) -> None:
        self._vault_path = Path(vault_path)
        self._backend = backend
        self._unlock_timeout = unlock_timeout
        self._locked = True
        self._key: bytes | None = None
        self._data: _VaultData = _VaultData()

        # Auto-initialize vault if it doesn't exist
        self._ensure_vault()

    # ------------------------------------------------------------------
    # Public API (safe for tool exposure — no raw values returned)
    # ------------------------------------------------------------------

    def unlock(self, master_key: str | None = None) -> bool:
        """Unlock the vault with a master key.

        If no master_key is provided, attempts to load from the key file
        adjacent to the vault (``<vault_path>.key``).
        """
        try:
            if master_key:
                self._key = bytes.fromhex(master_key)
            else:
                key_path = self._vault_path.with_suffix(".key")
                if key_path.exists():
                    self._key = bytes.fromhex(key_path.read_text(encoding="utf-8").strip())
                else:
                    logger.warning("vault_no_key_file", path=str(key_path))
                    return False

            if len(self._key) != _KEY_BYTES:
                logger.error("vault_invalid_key_length", length=len(self._key))
                self._key = None
                return False

            # Try to load and decrypt vault data to verify key
            self._load_vault()
            self._locked = False
            logger.info("vault_unlocked", backend=self._backend)
            return True
        except Exception as e:
            logger.error("vault_unlock_failed", error=str(e))
            self._key = None
            return False

    def lock(self) -> None:
        """Lock the vault — clears the key from memory."""
        self._key = None
        self._locked = True
        self._data = _VaultData()
        logger.info("vault_locked")

    async def store(self, name: str, value: str, description: str = "") -> CredentialRef:
        """Store a credential in the vault.

        The raw value is encrypted and never returned after storage.
        """
        if self._locked:
            msg = "Vault is locked — unlock first"
            raise RuntimeError(msg)

        self._load_vault()

        self._data.credentials[name] = {
            "encrypted_value": self._encrypt(value, aad=f"credential:{name}"),
            "description": description,
            "created_at": datetime.now(tz=UTC).isoformat(),
        }

        self._save_vault()
        logger.info("credential_stored", name=name)

        return CredentialRef(
            name=name,
            backend=self._backend,
            description=description,
            created_at=self._data.credentials[name]["created_at"],
        )

    def resolve(self, name: str) -> str:
        """Resolve a credential name to its raw value.

        INTERNAL ONLY — this method is never exposed as an agent tool.
        Used by other integration clients to retrieve API keys.
        """
        if self._locked:
            msg = "Vault is locked — unlock first"
            raise RuntimeError(msg)

        self._load_vault()

        if name not in self._data.credentials:
            msg = f"Credential '{name}' not found"
            raise KeyError(msg)

        return self._decrypt(self._data.credentials[name]["encrypted_value"], aad=f"credential:{name}")

    async def list_credentials(self) -> list[CredentialRef]:
        """List stored credential names and metadata (no raw values)."""
        if self._locked:
            msg = "Vault is locked — unlock first"
            raise RuntimeError(msg)

        self._load_vault()

        refs = []
        for name, meta in self._data.credentials.items():
            refs.append(
                CredentialRef(
                    name=name,
                    backend=self._backend,
                    description=meta.get("description", ""),
                    created_at=meta.get("created_at", ""),
                )
            )
        return refs

    async def delete(self, name: str) -> bool:
        """Delete a credential from the vault."""
        if self._locked:
            msg = "Vault is locked — unlock first"
            raise RuntimeError(msg)

        self._load_vault()

        if name not in self._data.credentials:
            return False

        del self._data.credentials[name]
        self._save_vault()
        logger.info("credential_deleted", name=name)
        return True

    async def get_status(self) -> VaultStatus:
        """Get vault status (safe for tool exposure)."""
        count = 0
        if not self._locked:
            try:
                self._load_vault()
                count = len(self._data.credentials)
            except Exception:
                pass

        return VaultStatus(
            backend=self._backend,
            locked=self._locked,
            credential_count=count,
            vault_path=str(self._vault_path),
        )

    # ------------------------------------------------------------------
    # Internal encryption / persistence
    # ------------------------------------------------------------------

    def _ensure_vault(self) -> None:
        """Create vault and key files if they don't exist."""
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)

        key_path = self._vault_path.with_suffix(".key")
        if not key_path.exists():
            # Generate a new master key — atomic creation with O_CREAT|O_EXCL
            # to prevent TOCTOU race conditions
            key = secrets.token_bytes(_KEY_BYTES)
            try:
                fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.write(fd, key.hex().encode("utf-8"))
                os.close(fd)
            except FileExistsError:
                # Another process created the key file between our check and open
                logger.info("vault_key_already_exists", path=str(key_path))
            else:
                logger.info("vault_key_generated", path=str(key_path))

        if not self._vault_path.exists():
            # Create empty encrypted vault
            self._key = bytes.fromhex(key_path.read_text(encoding="utf-8").strip())
            self._data = _VaultData()
            self._save_vault()
            self._key = None  # Re-lock
            logger.info("vault_created", path=str(self._vault_path))

    def _encrypt(self, plaintext: str, aad: str = "openclaw-vault-v1") -> str:
        """Encrypt a string with AES-256-GCM, return hex(nonce + ciphertext).

        Uses Associated Authenticated Data (AAD) to bind ciphertext to context,
        preventing ciphertext swapping attacks.
        """
        if not self._key:
            msg = "No encryption key loaded"
            raise RuntimeError(msg)

        aesgcm = AESGCM(self._key)
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return (nonce + ct).hex()

    def _decrypt(self, hex_data: str, aad: str = "openclaw-vault-v1") -> str:
        """Decrypt hex(nonce + ciphertext) with AES-256-GCM.

        The AAD must match what was used during encryption.
        """
        if not self._key:
            msg = "No encryption key loaded"
            raise RuntimeError(msg)

        raw = bytes.fromhex(hex_data)
        nonce = raw[:_NONCE_BYTES]
        ct = raw[_NONCE_BYTES:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ct, aad.encode("utf-8")).decode("utf-8")

    def _load_vault(self) -> None:
        """Load and decrypt the vault file."""
        if not self._vault_path.exists():
            self._data = _VaultData()
            return

        encrypted = self._vault_path.read_bytes()
        if not encrypted:
            self._data = _VaultData()
            return

        plaintext = self._decrypt(encrypted.decode("utf-8"))
        raw = json.loads(plaintext)
        self._data = _VaultData(
            version=raw.get("version", 1),
            credentials=raw.get("credentials", {}),
        )

    def _save_vault(self) -> None:
        """Encrypt and atomically write the vault file."""
        plaintext = json.dumps(
            {
                "version": self._data.version,
                "credentials": self._data.credentials,
            },
            indent=2,
        )
        encrypted = self._encrypt(plaintext)

        # Atomic write via temp file + rename
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._vault_path.parent),
            suffix=".tmp",
        )
        try:
            os.write(tmp_fd, encrypted.encode("utf-8"))
            os.close(tmp_fd)
            Path(tmp_path).replace(self._vault_path)
            # Restrict vault file permissions
            self._vault_path.chmod(0o600)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
