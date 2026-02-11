"""Composio brokered credential execution client.

Composio handles OAuth handshakes and token management on its own infrastructure.
The agent only sees reference IDs — raw OAuth tokens never enter the LLM context.
Supports 350+ app integrations (Slack, Google Calendar, Jira, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from openclaw.integrations import check_response_size, validate_id

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://backend.composio.dev/api/v2"


@dataclass
class ComposioApp:
    """A Composio-supported application."""

    key: str
    name: str
    description: str = ""
    categories: list[str] = field(default_factory=list)
    connected: bool = False


@dataclass
class ComposioAction:
    """An action available for a Composio app."""

    name: str
    display_name: str
    description: str = ""
    app_key: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComposioExecutionResult:
    """Result of executing a Composio action."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class ComposioClient:
    """Client for the Composio brokered credential execution API.

    Composio manages OAuth flows externally so that agents never handle
    raw access tokens. The agent sends action requests with reference IDs
    and receives structured results.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
        )

    async def list_apps(self) -> list[ComposioApp]:
        """List available Composio app integrations."""
        try:
            resp = await self._client.get(f"{self._base_url}/apps")
            resp.raise_for_status()
            check_response_size(resp.content, context="composio_list_apps")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("composio_list_apps_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("composio_list_apps_error", error=str(e))
            raise

        apps = []
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            apps.append(
                ComposioApp(
                    key=item.get("key", item.get("appId", "")),
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    categories=item.get("categories", []),
                    connected=item.get("connected", False),
                )
            )

        logger.info("composio_apps_listed", count=len(apps))
        return apps

    async def list_actions(self, app_key: str) -> list[ComposioAction]:
        """List available actions for a specific app."""
        try:
            resp = await self._client.get(
                f"{self._base_url}/actions",
                params={"appNames": app_key},
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="composio_list_actions")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("composio_list_actions_error", status=e.response.status_code, app=app_key)
            raise
        except Exception as e:
            logger.error("composio_list_actions_error", error=str(e), app=app_key)
            raise

        actions = []
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            actions.append(
                ComposioAction(
                    name=item.get("name", ""),
                    display_name=item.get("displayName", item.get("display_name", "")),
                    description=item.get("description", ""),
                    app_key=item.get("appKey", item.get("app_key", app_key)),
                    parameters=item.get("parameters", {}),
                )
            )

        logger.info("composio_actions_listed", app=app_key, count=len(actions))
        return actions

    async def execute_action(
        self,
        action_name: str,
        params: dict[str, Any] | None = None,
        entity_id: str = "default",
    ) -> ComposioExecutionResult:
        """Execute an action via Composio (brokered credentials).

        The OAuth token is managed by Composio — the agent never sees it.
        """
        action_name = validate_id(action_name, "action_name")
        payload: dict[str, Any] = {
            "actionName": action_name,
            "input": params or {},
            "entityId": entity_id,
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/actions/{action_name}/execute",
                json=payload,
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="composio_execute")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("composio_execute_error", status=e.response.status_code, action=action_name)
            return ComposioExecutionResult(success=False, error=f"HTTP {e.response.status_code}")
        except ValueError as e:
            logger.error("composio_execute_error", error=str(e), action=action_name)
            return ComposioExecutionResult(success=False, error=str(e))
        except Exception as e:
            logger.error("composio_execute_error", error=str(e), action=action_name)
            return ComposioExecutionResult(success=False, error=str(e))

        success = data.get("successfull", data.get("successful", False))
        logger.info("composio_action_executed", action=action_name, success=success)

        return ComposioExecutionResult(
            success=success,
            data=data.get("data", {}),
            error=data.get("error", ""),
        )

    async def get_connected_apps(self) -> list[ComposioApp]:
        """List only apps where the user has active connections."""
        try:
            resp = await self._client.get(f"{self._base_url}/connectedAccounts")
            resp.raise_for_status()
            check_response_size(resp.content, context="composio_connected_apps")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("composio_connected_apps_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("composio_connected_apps_error", error=str(e))
            raise

        apps = []
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            apps.append(
                ComposioApp(
                    key=item.get("appUniqueId", item.get("appId", "")),
                    name=item.get("appName", ""),
                    connected=True,
                )
            )

        logger.info("composio_connected_apps", count=len(apps))
        return apps

    async def close(self) -> None:
        await self._client.aclose()
