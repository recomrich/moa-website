"""Portfolio tracking - capital, balances, and performance metrics."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class PortfolioSnapshot:
    """Point-in-time snapshot of portfolio value."""

    timestamp: float
    total_value: float
    spot_value: float
    perps_value: float
    unrealized_pnl: float
    realized_pnl: float


class Portfolio:
    """Tracks portfolio value and performance over time."""

    def __init__(self, initial_capital: float = 10000.0) -> None:
        self._initial_capital = initial_capital
        self._paper_balance = initial_capital
        self._total_value = initial_capital
        self._spot_value = 0.0
        self._perps_value = 0.0
        self._unrealized_pnl = 0.0
        self._realized_pnl = 0.0
        self._daily_start_value = initial_capital
        self._daily_start_time = time.time()
        self._snapshots: list[PortfolioSnapshot] = []
        self._trade_results: list[dict] = []

    def update_from_exchange(self, client: Any) -> None:
        """Update portfolio values from live exchange data."""
        try:
            user_state = client.get_user_state()
            if not user_state:
                return

            account_value = float(
                user_state.get("marginSummary", {}).get("accountValue", 0)
            )
            self._total_value = account_value

            # Perps positions value
            total_position_value = float(
                user_state.get("marginSummary", {}).get(
                    "totalNtlPos", 0
                )
            )
            self._perps_value = total_position_value

            # Spot balances
            spot_balances = client.get_spot_balances()
            self._spot_value = sum(
                float(b.get("total", 0)) for b in spot_balances
            )

            self._take_snapshot()

        except Exception as e:
            logger.error(f"Failed to update portfolio from exchange: {e}")

    def update_paper(
        self, unrealized_pnl: float, realized_pnl_delta: float = 0.0
    ) -> None:
        """Update portfolio in paper trading mode."""
        self._realized_pnl += realized_pnl_delta
        self._unrealized_pnl = unrealized_pnl
        self._paper_balance += realized_pnl_delta
        self._total_value = self._paper_balance + unrealized_pnl
        self._take_snapshot()

    def record_trade(self, trade_result: dict) -> None:
        """Record a completed trade result."""
        self._trade_results.append(trade_result)
        pnl = trade_result.get("pnl", 0)
        self.update_paper(self._unrealized_pnl, pnl)

    def _take_snapshot(self) -> None:
        """Record a portfolio snapshot."""
        self._snapshots.append(
            PortfolioSnapshot(
                timestamp=time.time(),
                total_value=self._total_value,
                spot_value=self._spot_value,
                perps_value=self._perps_value,
                unrealized_pnl=self._unrealized_pnl,
                realized_pnl=self._realized_pnl,
            )
        )
        # Keep last 10000 snapshots
        if len(self._snapshots) > 10000:
            self._snapshots = self._snapshots[-5000:]

    def check_new_day(self) -> None:
        """Reset daily tracking at the start of a new day."""
        now = time.time()
        if now - self._daily_start_time >= 86400:
            self._daily_start_value = self._total_value
            self._daily_start_time = now

    @property
    def total_value(self) -> float:
        return self._total_value

    @property
    def paper_balance(self) -> float:
        return self._paper_balance

    @property
    def daily_pnl(self) -> float:
        return self._total_value - self._daily_start_value

    @property
    def daily_pnl_pct(self) -> float:
        if self._daily_start_value == 0:
            return 0.0
        return (self.daily_pnl / self._daily_start_value) * 100

    @property
    def total_pnl(self) -> float:
        return self._total_value - self._initial_capital

    @property
    def total_pnl_pct(self) -> float:
        if self._initial_capital == 0:
            return 0.0
        return (self.total_pnl / self._initial_capital) * 100

    def get_equity_curve(self, limit: int = 500) -> list[dict]:
        """Get equity curve data for charting."""
        snapshots = self._snapshots[-limit:]
        return [
            {
                "timestamp": s.timestamp,
                "value": round(s.total_value, 2),
            }
            for s in snapshots
        ]

    def get_trade_stats(self) -> dict:
        """Calculate trading performance statistics."""
        if not self._trade_results:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
            }

        wins = [t for t in self._trade_results if t.get("pnl", 0) > 0]
        losses = [t for t in self._trade_results if t.get("pnl", 0) <= 0]

        total_wins = sum(t["pnl"] for t in wins) if wins else 0
        total_losses = abs(sum(t["pnl"] for t in losses)) if losses else 0

        return {
            "total_trades": len(self._trade_results),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(
                (len(wins) / len(self._trade_results)) * 100, 1
            ),
            "avg_win": round(total_wins / len(wins), 4) if wins else 0.0,
            "avg_loss": round(
                total_losses / len(losses), 4
            ) if losses else 0.0,
            "total_pnl": round(
                sum(t.get("pnl", 0) for t in self._trade_results), 4
            ),
            "profit_factor": round(
                total_wins / total_losses, 2
            ) if total_losses > 0 else float("inf"),
        }

    def get_summary(self) -> dict:
        """Get full portfolio summary."""
        return {
            "initial_capital": self._initial_capital,
            "total_value": round(self._total_value, 2),
            "paper_balance": round(self._paper_balance, 2),
            "unrealized_pnl": round(self._unrealized_pnl, 4),
            "realized_pnl": round(self._realized_pnl, 4),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 2),
            "trade_stats": self.get_trade_stats(),
        }
