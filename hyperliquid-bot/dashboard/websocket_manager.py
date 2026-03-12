"""
Gestionnaire WebSocket — diffusion des données en temps réel aux clients.

Maintient la liste des connexions WebSocket actives et diffuse
les mises à jour de marché à tous les clients connectés.
"""

import json
from typing import Any

from fastapi import WebSocket
from loguru import logger


class WebSocketManager:
    """
    Gestionnaire des connexions WebSocket pour le dashboard temps réel.

    Maintient un pool de connexions actives et diffuse les messages
    JSON à tous les clients connectés simultanément.
    """

    def __init__(self) -> None:
        """Initialise le gestionnaire WebSocket."""
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accepte et enregistre une nouvelle connexion WebSocket.

        Args:
            websocket: Connexion WebSocket entrante.
        """
        await websocket.accept()
        self._connections.append(websocket)
        logger.debug(
            f"WebSocket connecté — total connexions: {len(self._connections)}"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Supprime une connexion WebSocket fermée.

        Args:
            websocket: Connexion à supprimer.
        """
        if websocket in self._connections:
            self._connections.remove(websocket)
            logger.debug(
                f"WebSocket déconnecté — total connexions: {len(self._connections)}"
            )

    async def broadcast(self, message_type: str, data: Any) -> None:
        """
        Diffuse un message JSON à toutes les connexions actives.

        Args:
            message_type: Type de message (ex: "prices", "positions", "stats").
            data: Données à envoyer (sérialisable en JSON).
        """
        if not self._connections:
            return

        payload = json.dumps({"type": message_type, "data": data})
        disconnected = []

        for websocket in self._connections:
            try:
                await websocket.send_text(payload)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket)

    async def send_to(self, websocket: WebSocket, message_type: str, data: Any) -> None:
        """
        Envoie un message à un client spécifique.

        Args:
            websocket: Connexion cible.
            message_type: Type de message.
            data: Données à envoyer.
        """
        try:
            payload = json.dumps({"type": message_type, "data": data})
            await websocket.send_text(payload)
        except Exception as exc:
            logger.debug(f"Erreur envoi WebSocket: {exc}")
            self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        """Nombre de connexions actives."""
        return len(self._connections)
