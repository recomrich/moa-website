"""
Serveur FastAPI — API REST et WebSocket pour le dashboard temps réel.

Expose les données du bot via une API REST et pousse les mises à jour
en temps réel aux clients connectés via WebSocket.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from dashboard.websocket_manager import WebSocketManager

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="HyperBot Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

ws_manager = WebSocketManager()

# Référence globale au bot (injectée depuis main.py)
_bot_ref = None


def set_bot_reference(bot: object) -> None:
    """
    Injecte la référence au bot principal dans le serveur.

    Args:
        bot: Instance du TradingBot.
    """
    global _bot_ref
    _bot_ref = bot


# Monter les fichiers statiques
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard() -> HTMLResponse:
    """Sert la page principale du dashboard."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard non trouvé</h1>", status_code=404)


@app.get("/api/status")
async def get_status() -> dict:
    """Retourne le statut général du bot."""
    if _bot_ref is None:
        return {"status": "déconnecté", "mode": "unknown"}

    return {
        "status": "actif" if getattr(_bot_ref, "is_running", False) else "arrêté",
        "mode": "paper" if getattr(_bot_ref, "paper_mode", True) else "LIVE",
        "uptime_seconds": getattr(_bot_ref, "uptime_seconds", 0),
    }


@app.get("/api/portfolio")
async def get_portfolio() -> dict:
    """Retourne le résumé du portefeuille."""
    if _bot_ref is None:
        return {}

    portfolio = getattr(_bot_ref, "portfolio", None)
    if portfolio is None:
        return {}

    return portfolio.get_summary()


@app.get("/api/positions")
async def get_positions() -> list:
    """Retourne les positions ouvertes."""
    if _bot_ref is None:
        return []

    position_manager = getattr(_bot_ref, "position_manager", None)
    if position_manager is None:
        return []

    return position_manager.to_dict_list()


@app.get("/api/trades")
async def get_trades(limit: int = 50) -> list:
    """
    Retourne l'historique des trades récents.

    Args:
        limit: Nombre max de trades (défaut: 50).
    """
    if _bot_ref is None:
        return []

    portfolio = getattr(_bot_ref, "portfolio", None)
    if portfolio is None:
        return []

    return portfolio.get_trade_history(limit=limit)


@app.get("/api/equity")
async def get_equity(points: int = 100) -> list:
    """
    Retourne l'historique de la courbe d'équity.

    Args:
        points: Nombre de points (défaut: 100).
    """
    if _bot_ref is None:
        return []

    portfolio = getattr(_bot_ref, "portfolio", None)
    if portfolio is None:
        return []

    return portfolio.get_equity_history(limit=points)


@app.get("/api/strategies")
async def get_strategies() -> list:
    """Retourne les statistiques des stratégies."""
    if _bot_ref is None:
        return []

    strategy_manager = getattr(_bot_ref, "strategy_manager", None)
    if strategy_manager is None:
        return []

    return strategy_manager.get_all_stats()


@app.get("/api/risk")
async def get_risk() -> dict:
    """Retourne les métriques de risque."""
    if _bot_ref is None:
        return {}

    risk_manager = getattr(_bot_ref, "risk_manager", None)
    if risk_manager is None:
        return {}

    return risk_manager.get_stats()


@app.get("/api/prices")
async def get_prices() -> dict:
    """Retourne les prix actuels de tous les actifs suivis."""
    if _bot_ref is None:
        return {}

    data_feed = getattr(_bot_ref, "data_feed", None)
    if data_feed is None:
        return {}

    return data_feed.get_all_prices()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Endpoint WebSocket pour les mises à jour temps réel.

    Envoie un snapshot initial, puis reçoit les messages du client.
    """
    await ws_manager.connect(websocket)
    logger.info(f"Client WebSocket connecté — total: {ws_manager.connection_count}")

    try:
        # Snapshot initial
        await _send_full_snapshot(websocket)

        while True:
            data = await websocket.receive_text()
            # Traitement des commandes client (ping, etc.)
            if data == "ping":
                await ws_manager.send_to(websocket, "pong", {})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info(f"Client WebSocket déconnecté — total: {ws_manager.connection_count}")


async def _send_full_snapshot(websocket: WebSocket) -> None:
    """Envoie un snapshot complet de l'état du bot à un nouveau client."""
    if _bot_ref is None:
        return

    try:
        portfolio = getattr(_bot_ref, "portfolio", None)
        position_manager = getattr(_bot_ref, "position_manager", None)
        strategy_manager = getattr(_bot_ref, "strategy_manager", None)
        risk_manager = getattr(_bot_ref, "risk_manager", None)
        data_feed = getattr(_bot_ref, "data_feed", None)

        if portfolio:
            await ws_manager.send_to(websocket, "portfolio", portfolio.get_summary())
            await ws_manager.send_to(websocket, "equity_history", portfolio.get_equity_history())
            await ws_manager.send_to(websocket, "trades", portfolio.get_trade_history())

        if position_manager:
            await ws_manager.send_to(websocket, "positions", position_manager.to_dict_list())

        if strategy_manager:
            await ws_manager.send_to(websocket, "strategies", strategy_manager.get_all_stats())

        if risk_manager:
            await ws_manager.send_to(websocket, "risk", risk_manager.get_stats())

        if data_feed:
            await ws_manager.send_to(websocket, "prices", data_feed.get_all_prices())

    except Exception as exc:
        logger.error(f"Erreur envoi snapshot initial: {exc}")


async def broadcast_update(update_type: str, data: object) -> None:
    """
    Diffuse une mise à jour à tous les clients WebSocket.

    Args:
        update_type: Type de mise à jour.
        data: Données à diffuser.
    """
    await ws_manager.broadcast(update_type, data)
