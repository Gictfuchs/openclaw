"""WebSocket chat route for real-time interaction with Fochs."""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from openclaw.core.events import (
    ErrorEvent,
    ResponseEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)

logger = structlog.get_logger()

router = APIRouter()

# Synthetic user ID for web dashboard sessions
WEB_USER_ID = 1_000_000


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Convert an AgentEvent to a JSON-serializable dict."""
    base = {"timestamp": event.timestamp.isoformat()}

    if isinstance(event, ThinkingEvent):
        return {**base, "type": "thinking", "content": event.content}
    if isinstance(event, ToolCallEvent):
        return {**base, "type": "tool_call", "tool": event.tool, "input": event.input}
    if isinstance(event, ToolResultEvent):
        # Truncate long tool outputs for the browser
        output = event.output
        if len(output) > 2000:
            output = output[:2000] + "\n... (gekuerzt)"
        return {**base, "type": "tool_result", "tool": event.tool, "output": output}
    if isinstance(event, ResponseEvent):
        return {**base, "type": "response", "content": event.content}
    if isinstance(event, ErrorEvent):
        return {
            **base,
            "type": "error",
            "message": event.message,
            "recoverable": event.recoverable,
        }
    # Fallback for unknown event types
    return {**base, "type": "unknown"}


@router.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat with the Fochs agent.

    Protocol:
    - Client sends: {"message": "user text here"}
    - Server streams: {"type": "thinking|tool_call|tool_result|response|error", ...}
    - Server sends {"type": "done"} when processing is complete
    """
    # Check auth via session cookie
    session = websocket.session
    if not session.get("authenticated", False):
        await websocket.close(code=4001, reason="Not authenticated")
        return

    await websocket.accept()
    logger.info("web_chat_connected")

    agent = websocket.app.state.fochs.get("agent")
    if not agent:
        await websocket.send_json({"type": "error", "message": "Agent nicht verfuegbar"})
        await websocket.close(code=4002, reason="Agent unavailable")
        return

    try:
        while True:
            # Receive user message
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                message = data.get("message", "").strip()
            except (json.JSONDecodeError, AttributeError):
                message = raw.strip()

            if not message:
                await websocket.send_json({"type": "error", "message": "Leere Nachricht"})
                continue

            logger.info("web_chat_message", length=len(message))

            # Stream agent events to the client
            try:
                async for event in agent.process(message, user_id=WEB_USER_ID):
                    if websocket.client_state != WebSocketState.CONNECTED:
                        break
                    await websocket.send_json(_event_to_dict(event))
            except Exception as e:
                logger.error("web_chat_agent_error", error=str(e), exc_info=True)
                if websocket.client_state == WebSocketState.CONNECTED:
                    # Never leak internal exception details to the client
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Ein interner Fehler ist aufgetreten. Bitte versuche es erneut.",
                        }
                    )

            # Signal completion
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("web_chat_disconnected")
    except Exception as e:
        logger.error("web_chat_unexpected_error", error=str(e))
