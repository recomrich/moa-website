"""Backtesting engine - runs strategies against historical data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger

from indicators.volatility import atr
from strategies.base_strategy import BaseStrategy, Signal


@dataclass
class BacktestTrade:
    """A trade recorded during backtesting."""

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    entry_time: str
    exit_time: str
    reason: str


@dataclass
class BacktestResult:
    """Result of a backtest run."""

    strategy_name: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)


class BacktestEngine:
    """Runs strategies against historical data to evaluate performance."""

    def __init__(
        self,
        initial_capital: float = 10000.0,
        risk_per_trade_pct: float = 1.0,
        commission_pct: float = 0.05,
    ) -> None:
        self._initial_capital = initial_capital
        self._risk_per_trade_pct = risk_per_trade_pct
        self._commission_pct = commission_pct

    def run(
        self,
        strategy: BaseStrategy,
        df: pd.DataFrame,
        symbol: str,
    ) -> BacktestResult:
        """Run a backtest for a strategy on historical data."""
        capital = self._initial_capital
        peak_capital = capital
        max_drawdown = 0.0
        trades: list[BacktestTrade] = []
        equity_curve: list[dict] = []
        position: Optional[dict] = None

        # Pre-compute ATR
        df_with_atr = df.copy()
        df_with_atr["ATR"] = atr(df)

        for i in range(50, len(df)):
            window = df.iloc[:i + 1]
            current = df.iloc[i]
            current_atr = df_with_atr.iloc[i].get("ATR", 0)
            timestamp = str(current.name)

            # Track equity
            equity_curve.append({"timestamp": timestamp, "value": round(capital, 2)})

            # Update max drawdown
            if capital > peak_capital:
                peak_capital = capital
            dd = ((peak_capital - capital) / peak_capital) * 100 if peak_capital > 0 else 0
            max_drawdown = max(max_drawdown, dd)

            # Check SL/TP if in position
            if position:
                close_price = current["close"]
                should_close = False
                reason = ""

                if position["side"] == "buy":
                    if close_price <= position["stop_loss"]:
                        should_close = True
                        reason = "stop_loss"
                        close_price = position["stop_loss"]
                    elif close_price >= position["take_profit"]:
                        should_close = True
                        reason = "take_profit"
                        close_price = position["take_profit"]
                else:
                    if close_price >= position["stop_loss"]:
                        should_close = True
                        reason = "stop_loss"
                        close_price = position["stop_loss"]
                    elif close_price <= position["take_profit"]:
                        should_close = True
                        reason = "take_profit"
                        close_price = position["take_profit"]

                if should_close:
                    trade = self._close_position(position, close_price, timestamp, reason)
                    capital += trade.pnl
                    commission = abs(trade.size * close_price) * (self._commission_pct / 100)
                    capital -= commission
                    trades.append(trade)
                    position = None
                continue

            # Generate signal
            signal = strategy.generate_signal(window)

            if signal == Signal.HOLD or pd.isna(current_atr) or current_atr == 0:
                continue

            entry_price = current["close"]
            side = "buy" if signal == Signal.BUY else "sell"
            sl = strategy.get_stop_loss(entry_price, current_atr, side)
            tp = strategy.get_take_profit(entry_price, current_atr, side)

            size = strategy.calculate_position_size(
                capital, self._risk_per_trade_pct, current_atr, entry_price
            )
            if size <= 0:
                continue

            commission = abs(size * entry_price) * (self._commission_pct / 100)
            capital -= commission

            position = {
                "side": side,
                "entry_price": entry_price,
                "size": size,
                "stop_loss": sl,
                "take_profit": tp,
                "entry_time": timestamp,
            }

        # Close any open position at end
        if position:
            close_price = df.iloc[-1]["close"]
            trade = self._close_position(
                position, close_price, str(df.index[-1]), "end_of_data"
            )
            capital += trade.pnl
            trades.append(trade)

        return self._build_result(
            strategy, symbol, df, capital, trades, equity_curve, max_drawdown
        )

    @staticmethod
    def _close_position(
        position: dict, close_price: float, timestamp: str, reason: str
    ) -> BacktestTrade:
        """Close a position and create a trade record."""
        if position["side"] == "buy":
            pnl = (close_price - position["entry_price"]) * position["size"]
        else:
            pnl = (position["entry_price"] - close_price) * position["size"]

        pnl_pct = (pnl / (position["entry_price"] * position["size"])) * 100

        return BacktestTrade(
            symbol="",
            side=position["side"],
            entry_price=position["entry_price"],
            exit_price=close_price,
            size=position["size"],
            pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct, 2),
            entry_time=position["entry_time"],
            exit_time=timestamp,
            reason=reason,
        )

    def _build_result(
        self,
        strategy: BaseStrategy,
        symbol: str,
        df: pd.DataFrame,
        final_capital: float,
        trades: list[BacktestTrade],
        equity_curve: list[dict],
        max_drawdown: float,
    ) -> BacktestResult:
        """Build the final backtest result."""
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        total_wins = sum(t.pnl for t in wins) if wins else 0
        total_losses = abs(sum(t.pnl for t in losses)) if losses else 0

        # Sharpe ratio (simplified)
        if trades:
            returns = [t.pnl_pct for t in trades]
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_return = variance ** 0.5
            sharpe = (avg_return / std_return) if std_return > 0 else 0.0
        else:
            sharpe = 0.0

        return BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            timeframe=strategy.timeframe,
            start_date=str(df.index[0]) if len(df) > 0 else "",
            end_date=str(df.index[-1]) if len(df) > 0 else "",
            initial_capital=self._initial_capital,
            final_capital=round(final_capital, 2),
            total_return_pct=round(
                ((final_capital - self._initial_capital) / self._initial_capital) * 100, 2
            ),
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=round((len(wins) / len(trades)) * 100, 1) if trades else 0.0,
            profit_factor=round(total_wins / total_losses, 2) if total_losses > 0 else float("inf"),
            max_drawdown_pct=round(max_drawdown, 2),
            sharpe_ratio=round(sharpe, 2),
            trades=trades,
            equity_curve=equity_curve,
        )
