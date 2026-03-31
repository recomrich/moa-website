"""Database CRUD operations for trades, orders, and snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from database.models import (
    OrderRecord,
    PortfolioSnapshot,
    StrategyRun,
    TradeRecord,
    init_db,
)


class Repository:
    """Data access layer for all database operations."""

    def __init__(self, db_url: str = "sqlite:///trading_bot.db") -> None:
        self._session_factory = init_db(db_url)

    def _session(self) -> Session:
        return self._session_factory()

    # --- Trades ---

    def save_trade(self, trade_data: dict) -> None:
        """Save a completed trade record."""
        with self._session() as session:
            try:
                record = TradeRecord(
                    symbol=trade_data.get("symbol", ""),
                    side=trade_data.get("side", ""),
                    size=trade_data.get("size", 0),
                    entry_price=trade_data.get("entry_price", 0),
                    exit_price=trade_data.get("exit_price"),
                    pnl=trade_data.get("pnl", 0),
                    pnl_pct=trade_data.get("pnl_pct", 0),
                    leverage=trade_data.get("leverage", 1),
                    strategy=trade_data.get("strategy"),
                    is_perp=trade_data.get("is_perp", False),
                    stop_loss=trade_data.get("stop_loss"),
                    take_profit=trade_data.get("take_profit"),
                    close_reason=trade_data.get("reason"),
                    opened_at=datetime.fromtimestamp(
                        trade_data.get("opened_at", datetime.utcnow().timestamp())
                    ),
                    closed_at=datetime.fromtimestamp(
                        trade_data.get("closed_at", datetime.utcnow().timestamp())
                    ),
                )
                session.add(record)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save trade: {e}")

    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        """Get recent trades ordered by close time."""
        with self._session() as session:
            trades = (
                session.query(TradeRecord)
                .order_by(TradeRecord.closed_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "size": t.size,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "leverage": t.leverage,
                    "strategy": t.strategy,
                    "close_reason": t.close_reason,
                    "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                }
                for t in trades
            ]

    def get_strategy_stats(self, strategy_name: str) -> dict:
        """Get performance stats for a specific strategy."""
        with self._session() as session:
            trades = (
                session.query(TradeRecord)
                .filter(TradeRecord.strategy == strategy_name)
                .all()
            )
            if not trades:
                return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

            wins = [t for t in trades if t.pnl > 0]
            return {
                "total": len(trades),
                "wins": len(wins),
                "losses": len(trades) - len(wins),
                "win_rate": round((len(wins) / len(trades)) * 100, 1),
                "total_pnl": round(sum(t.pnl for t in trades), 4),
            }

    # --- Orders ---

    def save_order(self, order_data: dict) -> None:
        """Save an order record."""
        with self._session() as session:
            try:
                record = OrderRecord(
                    order_id=order_data.get("order_id", ""),
                    symbol=order_data.get("symbol", ""),
                    side=order_data.get("side", ""),
                    order_type=order_data.get("order_type", ""),
                    size=order_data.get("size", 0),
                    price=order_data.get("price"),
                    fill_price=order_data.get("fill_price"),
                    status=order_data.get("status", ""),
                    strategy=order_data.get("strategy"),
                )
                session.add(record)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save order: {e}")

    # --- Strategy Runs ---

    def save_strategy_run(
        self, strategy_name: str, symbol: str, timeframe: str, signal: str
    ) -> None:
        """Record a strategy execution."""
        with self._session() as session:
            try:
                run = StrategyRun(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    signal=signal,
                )
                session.add(run)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save strategy run: {e}")

    # --- Portfolio Snapshots ---

    def save_portfolio_snapshot(self, snapshot_data: dict) -> None:
        """Save a portfolio value snapshot."""
        with self._session() as session:
            try:
                snap = PortfolioSnapshot(
                    total_value=snapshot_data.get("total_value", 0),
                    spot_value=snapshot_data.get("spot_value", 0),
                    perps_value=snapshot_data.get("perps_value", 0),
                    unrealized_pnl=snapshot_data.get("unrealized_pnl", 0),
                    realized_pnl=snapshot_data.get("realized_pnl", 0),
                )
                session.add(snap)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save portfolio snapshot: {e}")

    def get_equity_curve(self, hours: int = 24) -> list[dict]:
        """Get portfolio equity curve for the last N hours."""
        with self._session() as session:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            snaps = (
                session.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.recorded_at >= cutoff)
                .order_by(PortfolioSnapshot.recorded_at)
                .all()
            )
            return [
                {
                    "timestamp": s.recorded_at.isoformat(),
                    "value": s.total_value,
                }
                for s in snaps
            ]
