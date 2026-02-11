"""Composio brokered credential execution tools for the agent."""

import json
from typing import Any

import structlog

from openclaw.integrations.composio import ComposioClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class ComposioAppsTool(BaseTool):
    """List available Composio app integrations."""

    name = "composio_apps"
    description = (
        "List available third-party app integrations via Composio. "
        "Shows which apps (Slack, Google Calendar, Jira, etc.) are available "
        "and which ones have active connections."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "connected_only": {
                "type": "boolean",
                "description": "If true, only show apps with active connections.",
            },
        },
        "required": [],
    }

    def __init__(self, client: ComposioClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        connected_only = kwargs.get("connected_only", False)

        try:
            if connected_only:
                apps = await self._client.get_connected_apps()
            else:
                apps = await self._client.list_apps()
        except Exception as e:
            return f"Failed to list Composio apps: {e}"

        if not apps:
            return "No Composio app integrations available."

        parts = [f"Composio App Integrations ({len(apps)}):\n"]
        for app in apps:
            status = " [connected]" if app.connected else ""
            desc = f" - {app.description}" if app.description else ""
            cats = f" [{', '.join(app.categories)}]" if app.categories else ""
            parts.append(f"  - {app.name} ({app.key}){status}{cats}{desc}")

        return "\n".join(parts)


class ComposioActionsTool(BaseTool):
    """List available actions for a Composio app."""

    name = "composio_actions"
    description = (
        "List available actions for a specific Composio app integration. "
        "Use this to discover what you can do with a connected app."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "app_key": {
                "type": "string",
                "description": "The app key (e.g. 'slack', 'google-calendar', 'jira').",
            },
        },
        "required": ["app_key"],
    }

    def __init__(self, client: ComposioClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        app_key = kwargs["app_key"]

        try:
            actions = await self._client.list_actions(app_key=app_key)
        except Exception as e:
            return f"Failed to list actions for '{app_key}': {e}"

        if not actions:
            return f"No actions available for app '{app_key}'."

        parts = [f"Actions for {app_key} ({len(actions)}):\n"]
        for action in actions:
            display = f" ({action.display_name})" if action.display_name else ""
            desc = f"\n    {action.description}" if action.description else ""
            parts.append(f"  - {action.name}{display}{desc}")

        return "\n".join(parts)


class ComposioExecuteTool(BaseTool):
    """Execute an action via Composio (brokered credentials)."""

    name = "composio_execute"
    description = (
        "Execute an action on a third-party app via Composio. "
        "Composio handles OAuth tokens — you never see raw credentials. "
        "Provide the action name and parameters as a JSON object."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "The action name to execute (from composio_actions).",
            },
            "params": {
                "type": "object",
                "description": "Parameters for the action as key-value pairs.",
            },
            "entity_id": {
                "type": "string",
                "description": "Entity ID for multi-user setups (default: 'default').",
            },
        },
        "required": ["action"],
    }

    def __init__(self, client: ComposioClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        action_name = kwargs["action"]
        params = kwargs.get("params", {})
        entity_id = kwargs.get("entity_id", "default")

        try:
            result = await self._client.execute_action(
                action_name=action_name,
                params=params,
                entity_id=entity_id,
            )
        except Exception as e:
            return f"Failed to execute action '{action_name}': {e}"

        if not result.success:
            return f"Action '{action_name}' failed: {result.error}"

        # Format result data
        parts = [f"Action '{action_name}' executed successfully."]
        if result.data:
            # Truncate large responses
            data_str = json.dumps(result.data, indent=2, ensure_ascii=False)
            if len(data_str) > 2000:
                data_str = data_str[:2000] + "\n... (truncated)"
            parts.append(f"\nResult:\n{data_str}")

        return "\n".join(parts)
