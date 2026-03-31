"""FastAPI dashboard server with REST API and WebSocket support."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from dashboard.websocket_manager import WebSocketManager

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Hyperliquid Trading Bot", version="1.0.0")
ws_manager = WebSocketManager()

# Reference to bot state (set by main.py)
_bot_state: dict[str, Any] = {}


def set_bot_state(state: dict[str, Any]) -> None:
    """Set the shared bot state reference."""
    global _bot_state
    _bot_state = state


# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """Serve the dashboard HTML."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status")
async def get_status():
    """Get bot status overview."""
    portfolio = _bot_state.get("portfolio")
    risk = _bot_state.get("risk_manager")

    return JSONResponse({
        "mode": _bot_state.get("mode", "paper"),
        "running": _bot_state.get("running", False),
        "portfolio": portfolio.get_summary() if portfolio else {},
        "risk": risk.get_risk_summary() if risk else {},
        "uptime": _bot_state.get("uptime", 0),
    })


@app.get("/api/positions")
async def get_positions():
    """Get all open positions."""
    position_manager = _bot_state.get("position_manager")
    if not position_manager:
        return JSONResponse([])

    positions = position_manager.get_all_positions()
    return JSONResponse([
        {
            "symbol": p.symbol,
            "side": p.side.value,
            "size": p.size,
            "entry_price": p.entry_price,
            "unrealized_pnl": round(p.unrealized_pnl, 4),
            "pnl_pct": p.pnl_pct,
            "leverage": p.leverage,
            "stop_loss": p.stop_loss,
            "take_profit": p.take_profit,
            "strategy": p.strategy_name,
        }
        for p in positions
    ])


@app.get("/api/trades")
async def get_trades():
    """Get recent trade history."""
    repo = _bot_state.get("repository")
    if repo:
        return JSONResponse(repo.get_recent_trades(50))

    position_manager = _bot_state.get("position_manager")
    if position_manager:
        return JSONResponse(position_manager.get_closed_positions(50))

    return JSONResponse([])


@app.get("/api/strategies")
async def get_strategies():
    """Get strategy statuses."""
    strategy_manager = _bot_state.get("strategy_manager")
    if not strategy_manager:
        return JSONResponse([])
    return JSONResponse(strategy_manager.get_all_statuses())


@app.get("/api/equity")
async def get_equity():
    """Get equity curve data."""
    portfolio = _bot_state.get("portfolio")
    if not portfolio:
        return JSONResponse([])
    return JSONResponse(portfolio.get_equity_curve())


@app.get("/api/prices")
async def get_prices():
    """Get current prices."""
    feed = _bot_state.get("feed")
    if not feed:
        return JSONResponse({})
    return JSONResponse(feed.last_prices)


@app.post("/api/strategy/{name}/toggle")
async def toggle_strategy(name: str):
    """Enable/disable a strategy."""
    strategy_manager = _bot_state.get("strategy_manager")
    if not strategy_manager:
        return JSONResponse({"error": "No strategy manager"}, status_code=500)

    strategy = strategy_manager.get_strategy(name)
    if not strategy:
        return JSONResponse({"error": f"Strategy '{name}' not found"}, status_code=404)

    strategy.enabled = not strategy.enabled
    status = "enabled" if strategy.enabled else "disabled"
    logger.info(f"Strategy {name} {status} via dashboard")
    return JSONResponse({"name": name, "enabled": strategy.enabled})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            logger.debug(f"WS received: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


async def broadcast_update(event: str, data: Any) -> None:
    """Broadcast an update to all connected dashboard clients."""
    await ws_manager.broadcast(event, data)


def run_dashboard(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the dashboard server (blocking)."""
    import uvicorn
    logger.info(f"Starting dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
