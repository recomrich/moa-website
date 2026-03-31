"""WebSocket connection manager for real-time dashboard updates."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket
from loguru import logger


class WebSocketManager:
    """Manages WebSocket connections and broadcasts updates."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logger.info(
            f"WebSocket client connected. "
            f"Total connections: {len(self._connections)}"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info(
            f"WebSocket client disconnected. "
            f"Total connections: {len(self._connections)}"
        )

    async def broadcast(self, event: str, data: Any) -> None:
        """Broadcast a message to all connected clients."""
        message = json.dumps({"event": event, "data": data})
        disconnected: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, event: str, data: Any) -> None:
        """Send a message to a specific client."""
        try:
            message = json.dumps({"event": event, "data": data})
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
            self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
