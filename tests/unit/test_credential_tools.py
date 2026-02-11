"""Tests for the ClosedClaw credential vault tools."""

import secrets
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.closedclaw import (
    ClosedClawClient,
    CredentialRef,
    VaultStatus,
)
from openclaw.tools.credential_tools import (
    CredentialListTool,
    CredentialStatusTool,
    CredentialStoreTool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Provide a temporary vault directory."""
    return tmp_path / "vault"


@pytest.fixture
def vault_client(vault_dir: Path) -> ClosedClawClient:
    """Create a real ClosedClawClient with a temp vault."""
    vault_path = str(vault_dir / "fochs.vault")
    client = ClosedClawClient(vault_path=vault_path)
    client.unlock()
    return client


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock ClosedClawClient."""
    return AsyncMock(spec=ClosedClawClient)


# ---------------------------------------------------------------------------
# Integration Client Tests
# ---------------------------------------------------------------------------


class TestClosedClawClient:
    """Tests for the ClosedClaw vault client itself."""

    def test_vault_creation(self, vault_dir: Path) -> None:
        """Vault and key files are created on init."""
        vault_path = vault_dir / "test.vault"
        ClosedClawClient(vault_path=str(vault_path))

        assert vault_path.exists()
        assert vault_path.with_suffix(".key").exists()

    def test_key_file_permissions(self, vault_dir: Path) -> None:
        """Key file has restricted permissions (owner-only)."""
        vault_path = vault_dir / "test.vault"
        ClosedClawClient(vault_path=str(vault_path))

        key_path = vault_path.with_suffix(".key")
        mode = oct(key_path.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_unlock_with_key_file(self, vault_dir: Path) -> None:
        """Vault unlocks using auto-generated key file."""
        vault_path = vault_dir / "test.vault"
        client = ClosedClawClient(vault_path=str(vault_path))

        assert client.unlock() is True

    def test_unlock_with_explicit_key(self, vault_dir: Path) -> None:
        """Vault unlocks with an explicitly provided master key."""
        vault_path = vault_dir / "test.vault"
        key = secrets.token_bytes(32).hex()

        # Write key file for vault creation
        vault_dir.mkdir(parents=True, exist_ok=True)
        key_path = vault_path.with_suffix(".key")
        key_path.write_text(key, encoding="utf-8")
        key_path.chmod(0o600)

        client = ClosedClawClient(vault_path=str(vault_path))
        assert client.unlock(master_key=key) is True

    def test_unlock_fails_with_wrong_key(self, vault_dir: Path) -> None:
        """Vault rejects incorrect master key."""
        vault_path = vault_dir / "test.vault"
        ClosedClawClient(vault_path=str(vault_path))

        # Create a new client with the existing vault
        client2 = ClosedClawClient(vault_path=str(vault_path))
        wrong_key = secrets.token_bytes(32).hex()
        assert client2.unlock(master_key=wrong_key) is False

    async def test_store_and_resolve(self, vault_client: ClosedClawClient) -> None:
        """Credentials can be stored and resolved."""
        ref = await vault_client.store("test_key", "secret_value_123", description="Test key")

        assert ref.name == "test_key"
        assert ref.description == "Test key"
        assert ref.backend == "vault-file"

        # Resolve returns the raw value (internal only)
        resolved = vault_client.resolve("test_key")
        assert resolved == "secret_value_123"

    async def test_resolve_missing_credential(self, vault_client: ClosedClawClient) -> None:
        """Resolving a non-existent credential raises KeyError."""
        with pytest.raises(KeyError, match="not found"):
            vault_client.resolve("nonexistent")

    async def test_resolve_while_locked(self, vault_dir: Path) -> None:
        """Resolving while locked raises RuntimeError."""
        vault_path = str(vault_dir / "test.vault")
        client = ClosedClawClient(vault_path=vault_path)
        # Don't unlock

        with pytest.raises(RuntimeError, match="locked"):
            client.resolve("anything")

    async def test_list_credentials(self, vault_client: ClosedClawClient) -> None:
        """List returns names and metadata without raw values."""
        await vault_client.store("key_a", "val_a", description="Key A")
        await vault_client.store("key_b", "val_b", description="Key B")

        creds = await vault_client.list_credentials()
        assert len(creds) == 2

        names = {c.name for c in creds}
        assert names == {"key_a", "key_b"}

        # Verify no raw values leak
        for cred in creds:
            assert "val_a" not in str(cred)
            assert "val_b" not in str(cred)

    async def test_delete_credential(self, vault_client: ClosedClawClient) -> None:
        """Credentials can be deleted."""
        await vault_client.store("to_delete", "secret")

        assert await vault_client.delete("to_delete") is True
        assert await vault_client.delete("to_delete") is False  # Already gone

        with pytest.raises(KeyError):
            vault_client.resolve("to_delete")

    async def test_get_status(self, vault_client: ClosedClawClient) -> None:
        """Status shows vault state."""
        await vault_client.store("key1", "val1")

        status = await vault_client.get_status()
        assert status.locked is False
        assert status.backend == "vault-file"
        assert status.credential_count == 1

    def test_lock_clears_key(self, vault_client: ClosedClawClient) -> None:
        """Locking clears the encryption key from memory."""
        vault_client.lock()

        assert vault_client._locked is True
        assert vault_client._key is None

    async def test_persistence_across_instances(self, vault_dir: Path) -> None:
        """Credentials persist across client instances."""
        vault_path = str(vault_dir / "persist.vault")

        # Store with first instance
        client1 = ClosedClawClient(vault_path=vault_path)
        client1.unlock()
        await client1.store("persistent_key", "persistent_value")
        client1.lock()

        # Resolve with second instance
        client2 = ClosedClawClient(vault_path=vault_path)
        client2.unlock()
        assert client2.resolve("persistent_key") == "persistent_value"

    async def test_special_characters_in_value(self, vault_client: ClosedClawClient) -> None:
        """Special characters in values are handled correctly."""
        special = 'key-with-special: "quotes", \\ backslash, \n newline, emoji'
        await vault_client.store("special", special)
        assert vault_client.resolve("special") == special


# ---------------------------------------------------------------------------
# Tool Tests (using mock client)
# ---------------------------------------------------------------------------


class TestCredentialListTool:
    async def test_execute_lists_credentials(self, mock_client: AsyncMock) -> None:
        mock_client.list_credentials.return_value = [
            CredentialRef(name="github_token", description="GitHub PAT", created_at="2025-01-01T00:00:00Z"),
            CredentialRef(name="brave_key", description="Brave Search API"),
        ]

        tool = CredentialListTool(client=mock_client)
        result = await tool.execute()

        assert "github_token" in result
        assert "GitHub PAT" in result
        assert "brave_key" in result
        assert "2" in result  # count

    async def test_execute_empty_vault(self, mock_client: AsyncMock) -> None:
        mock_client.list_credentials.return_value = []

        tool = CredentialListTool(client=mock_client)
        result = await tool.execute()

        assert "No credentials" in result

    async def test_execute_vault_locked(self, mock_client: AsyncMock) -> None:
        mock_client.list_credentials.side_effect = RuntimeError("Vault is locked")

        tool = CredentialListTool(client=mock_client)
        result = await tool.execute()

        assert "locked" in result.lower()

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = CredentialListTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "credential_list"
        assert "input_schema" in defn


class TestCredentialStoreTool:
    async def test_execute_stores_credential(self, mock_client: AsyncMock) -> None:
        mock_client.store.return_value = CredentialRef(
            name="new_key",
            backend="vault-file",
            description="A new key",
        )

        tool = CredentialStoreTool(client=mock_client)
        result = await tool.execute(name="new_key", value="secret123", description="A new key")

        assert "stored successfully" in result
        assert "new_key" in result
        assert "secret123" not in result  # Raw value must NEVER appear

    async def test_execute_empty_name(self, mock_client: AsyncMock) -> None:
        tool = CredentialStoreTool(client=mock_client)
        result = await tool.execute(name="  ", value="secret")

        assert "empty" in result.lower()
        mock_client.store.assert_not_called()

    async def test_execute_empty_value(self, mock_client: AsyncMock) -> None:
        tool = CredentialStoreTool(client=mock_client)
        result = await tool.execute(name="key", value="  ")

        assert "empty" in result.lower()
        mock_client.store.assert_not_called()

    async def test_execute_rejects_path_traversal_name(self, mock_client: AsyncMock) -> None:
        """Credential names with path separators must be rejected."""
        tool = CredentialStoreTool(client=mock_client)
        result = await tool.execute(name="../../etc/passwd", value="secret")

        assert "invalid characters" in result.lower()
        mock_client.store.assert_not_called()

    async def test_execute_rejects_special_chars_name(self, mock_client: AsyncMock) -> None:
        """Credential names with special characters must be rejected."""
        tool = CredentialStoreTool(client=mock_client)

        for bad_name in ["key with spaces", "key/slash", "key\x00null", "key;drop"]:
            result = await tool.execute(name=bad_name, value="secret")
            assert "invalid characters" in result.lower(), f"Expected rejection for name: {bad_name!r}"
            mock_client.store.assert_not_called()

    async def test_execute_accepts_valid_names(self, mock_client: AsyncMock) -> None:
        """Credential names with safe patterns must be accepted."""
        mock_client.store.return_value = CredentialRef(name="test", backend="vault-file")

        tool = CredentialStoreTool(client=mock_client)

        for good_name in ["github_token", "brave-api-key", "KEY.v2", "api_key_123"]:
            mock_client.store.reset_mock()
            mock_client.store.return_value = CredentialRef(name=good_name, backend="vault-file")
            result = await tool.execute(name=good_name, value="secret")
            assert "stored successfully" in result, f"Expected success for name: {good_name!r}"

    async def test_execute_vault_locked(self, mock_client: AsyncMock) -> None:
        mock_client.store.side_effect = RuntimeError("Vault is locked")

        tool = CredentialStoreTool(client=mock_client)
        result = await tool.execute(name="key", value="val")

        assert "locked" in result.lower()

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = CredentialStoreTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "credential_store"
        assert "name" in defn["input_schema"]["properties"]
        assert "value" in defn["input_schema"]["properties"]


class TestCredentialStatusTool:
    async def test_execute_shows_status(self, mock_client: AsyncMock) -> None:
        mock_client.get_status.return_value = VaultStatus(
            backend="vault-file",
            locked=False,
            credential_count=3,
            vault_path="/tmp/fochs/vault",
        )

        tool = CredentialStatusTool(client=mock_client)
        result = await tool.execute()

        assert "UNLOCKED" in result
        assert "vault-file" in result
        assert "3" in result

    async def test_execute_does_not_leak_vault_path(self, mock_client: AsyncMock) -> None:
        """Vault path must NEVER be exposed to the LLM agent."""
        mock_client.get_status.return_value = VaultStatus(
            backend="vault-file",
            locked=False,
            credential_count=3,
            vault_path="/home/user/.fochs/vault/fochs.vault",
        )

        tool = CredentialStatusTool(client=mock_client)
        result = await tool.execute()

        assert "/home/user" not in result
        assert "fochs.vault" not in result
        assert "vault_path" not in result.lower()

    async def test_execute_locked_status(self, mock_client: AsyncMock) -> None:
        mock_client.get_status.return_value = VaultStatus(
            backend="vault-file",
            locked=True,
            credential_count=0,
        )

        tool = CredentialStatusTool(client=mock_client)
        result = await tool.execute()

        assert "LOCKED" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.get_status.side_effect = Exception("Vault corrupt")

        tool = CredentialStatusTool(client=mock_client)
        result = await tool.execute()

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = CredentialStatusTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "credential_status"
        assert "input_schema" in defn
