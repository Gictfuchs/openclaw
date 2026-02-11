"""WebSocket chat route for real-time interaction with Fochs.

Security:
- Session-based authentication before accepting connections
- Token-bucket rate limiting per connection (20 msg/min)
- Message size limit to prevent memory exhaustion (16 KB)
- Global connection limit per session to prevent rate-limit bypass via parallel connections
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
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

# WebSocket rate limiting: max messages per window
_WS_RATE_LIMIT = 20  # messages
_WS_RATE_WINDOW = 60.0  # seconds

# Maximum message size (16 KB) — prevents large payload attacks
_WS_MAX_MESSAGE_SIZE = 16 * 1024

# Global WebSocket connection limits
_WS_MAX_CONNECTIONS_GLOBAL = 20
_WS_MAX_CONNECTIONS_PER_IP = 3

# Active connection tracking: IP -> count
_ws_connections: dict[str, int] = defaultdict(int)
_ws_total_connections = 0


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


def _get_ws_client_ip(websocket: WebSocket) -> str:
    """Extract client IP from WebSocket connection."""
    forwarded = websocket.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = websocket.client
    return client.host if client else "unknown"


@router.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat with the Fochs agent.

    Protocol:
    - Client sends: {"message": "user text here"}
    - Server streams: {"type": "thinking|tool_call|tool_result|response|error", ...}
    - Server sends {"type": "done"} when processing is complete
    """
    global _ws_total_connections  # noqa: PLW0603

    # Check auth via session cookie
    session = websocket.session
    if not session.get("authenticated", False):
        await websocket.close(code=4001, reason="Not authenticated")
        return

    # --- Connection limit check (before accept) ---
    client_ip = _get_ws_client_ip(websocket)

    if _ws_total_connections >= _WS_MAX_CONNECTIONS_GLOBAL:
        logger.warning("ws_global_limit_reached", total=_ws_total_connections)
        await websocket.close(code=4003, reason="Too many connections")
        return

    if _ws_connections[client_ip] >= _WS_MAX_CONNECTIONS_PER_IP:
        logger.warning("ws_per_ip_limit_reached", ip=client_ip, count=_ws_connections[client_ip])
        await websocket.close(code=4003, reason="Too many connections from this IP")
        return

    # Track connection
    _ws_connections[client_ip] += 1
    _ws_total_connections += 1

    await websocket.accept()
    logger.info("web_chat_connected", ip=client_ip, total=_ws_total_connections)

    try:
        agent = websocket.app.state.fochs.get("agent")
        if not agent:
            await websocket.send_json({"type": "error", "message": "Agent nicht verfuegbar"})
            await websocket.close(code=4002, reason="Agent unavailable")
            return

        # Per-connection rate limiter (sliding window)
        message_timestamps: list[float] = []

        while True:
            # Receive user message
            raw = await websocket.receive_text()

            # --- Message size check ---
            if len(raw) > _WS_MAX_MESSAGE_SIZE:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Nachricht zu gross (max {_WS_MAX_MESSAGE_SIZE // 1024} KB).",
                    }
                )
                continue

            # --- Rate limiting ---
            now = time.monotonic()
            cutoff = now - _WS_RATE_WINDOW
            message_timestamps[:] = [t for t in message_timestamps if t > cutoff]
            if len(message_timestamps) >= _WS_RATE_LIMIT:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Rate limit: max {_WS_RATE_LIMIT} Nachrichten pro Minute.",
                    }
                )
                logger.warning("ws_rate_limited")
                continue
            message_timestamps.append(now)

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
    finally:
        # Always release connection tracking
        _ws_connections[client_ip] = max(0, _ws_connections[client_ip] - 1)
        if _ws_connections[client_ip] == 0:
            _ws_connections.pop(client_ip, None)
        _ws_total_connections = max(0, _ws_total_connections - 1)
        logger.info("ws_connection_released", ip=client_ip, total=_ws_total_connections)
