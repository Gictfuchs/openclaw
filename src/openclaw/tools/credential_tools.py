"""Credential vault tools for the agent.

Security invariant: These tools NEVER return raw credential values.
Only names, metadata, and status information are exposed to the LLM.
"""

import re
from typing import Any

import structlog

from openclaw.integrations.closedclaw import ClosedClawClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class CredentialListTool(BaseTool):
    """List stored credentials (names and metadata only)."""

    name = "credential_list"
    description = (
        "List all credentials stored in the vault. "
        "Returns names and descriptions only — never raw values. "
        "The vault must be unlocked first."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, client: ClosedClawClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        try:
            credentials = await self._client.list_credentials()
        except RuntimeError as e:
            return f"Vault error: {e}"
        except Exception as e:
            return f"Failed to list credentials: {e}"

        if not credentials:
            return "No credentials stored in the vault."

        parts = [f"Stored credentials ({len(credentials)}):\n"]
        for cred in credentials:
            desc = f" - {cred.description}" if cred.description else ""
            created = f" (created: {cred.created_at})" if cred.created_at else ""
            parts.append(f"  - {cred.name}{desc}{created}")

        return "\n".join(parts)


class CredentialStoreTool(BaseTool):
    """Store a new credential in the vault."""

    name = "credential_store"
    description = (
        "Store a credential (API key, token, password) in the encrypted vault. "
        "The value is encrypted and can never be retrieved by the agent. "
        "Other integrations can resolve it internally by name."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique name for the credential (e.g. 'github_token', 'brave_api_key').",
            },
            "value": {
                "type": "string",
                "description": "The secret value to store. Will be encrypted immediately.",
            },
            "description": {
                "type": "string",
                "description": "Optional description of what this credential is for.",
            },
        },
        "required": ["name", "value"],
    }

    def __init__(self, client: ClosedClawClient) -> None:
        self._client = client

    # Credential names: alphanumeric, hyphens, underscores, dots. Max 128 chars.
    _NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.\-]{1,128}$")

    async def execute(self, **kwargs: Any) -> str:
        name = kwargs["name"].strip()
        value = kwargs["value"]
        description = kwargs.get("description", "")

        if not name:
            return "Error: Credential name cannot be empty."

        if not self._NAME_PATTERN.match(name):
            return (
                "Error: Credential name contains invalid characters. "
                "Allowed: letters, digits, hyphens, underscores, dots. Max 128 chars."
            )

        if not value.strip():
            return "Error: Credential value cannot be empty."

        try:
            ref = await self._client.store(name=name, value=value, description=description)
        except RuntimeError as e:
            return f"Vault error: {e}"
        except Exception as e:
            return f"Failed to store credential: {e}"

        return (
            f"Credential '{ref.name}' stored successfully in vault "
            f"(backend: {ref.backend}). The raw value is now encrypted "
            f"and will never be returned."
        )


class CredentialStatusTool(BaseTool):
    """Get vault status information."""

    name = "credential_status"
    description = (
        "Get the current status of the credential vault. "
        "Shows whether it's locked/unlocked, the backend type, and credential count."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, client: ClosedClawClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        try:
            status = await self._client.get_status()
        except Exception as e:
            return f"Failed to get vault status: {e}"

        state = "LOCKED" if status.locked else "UNLOCKED"
        parts = [
            f"Credential Vault Status: {state}",
            f"  Backend: {status.backend}",
            f"  Stored credentials: {status.credential_count}",
        ]
        return "\n".join(parts)
