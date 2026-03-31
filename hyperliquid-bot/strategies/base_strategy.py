"""Abstract base class for all trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

import pandas as pd


class Signal(str, Enum):
    """Trading signal types."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class BaseStrategy(ABC):
    """Base class that all strategies must inherit from."""

    def __init__(self, name: str, timeframe: str, params: dict | None = None) -> None:
        self.name = name
        self.timeframe = timeframe
        self.params = params or {}
        self.enabled = True
        self._signal_count = 0
        self._win_count = 0
        self._loss_count = 0

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Analyze data and generate a trading signal.

        Args:
            df: DataFrame with OHLCV data and indicators.

        Returns:
            Signal (BUY, SELL, or HOLD).
        """

    def calculate_position_size(
        self, capital: float, risk_pct: float, atr: float, entry_price: float
    ) -> float:
        """Calculate position size based on risk and ATR.

        Args:
            capital: Available capital.
            risk_pct: Percentage of capital to risk (e.g. 1.0 = 1%).
            atr: Current ATR value for volatility-adjusted sizing.
            entry_price: Expected entry price.

        Returns:
            Position size in base asset units.
        """
        risk_amount = capital * (risk_pct / 100)
        stop_distance = atr * 1.5  # Default 1.5x ATR for stop

        if stop_distance == 0:
            return 0.0

        size = risk_amount / stop_distance
        return round(size, 6)

    def get_stop_loss(
        self, entry_price: float, atr: float, side: str = "buy"
    ) -> float:
        """Calculate stop-loss price using ATR.

        Args:
            entry_price: Entry price of the position.
            atr: Current ATR value.
            side: 'buy' or 'sell'.

        Returns:
            Stop-loss price.
        """
        multiplier = self.params.get("sl_atr_multiplier", 1.5)
        if side == "buy":
            return round(entry_price - (atr * multiplier), 6)
        return round(entry_price + (atr * multiplier), 6)

    def get_take_profit(
        self, entry_price: float, atr: float, side: str = "buy", ratio: float = 2.0
    ) -> float:
        """Calculate take-profit price using ATR and R:R ratio.

        Args:
            entry_price: Entry price of the position.
            atr: Current ATR value.
            side: 'buy' or 'sell'.
            ratio: Risk/reward ratio (default 2.0 = 2:1).

        Returns:
            Take-profit price.
        """
        sl_multiplier = self.params.get("sl_atr_multiplier", 1.5)
        tp_distance = atr * sl_multiplier * ratio
        if side == "buy":
            return round(entry_price + tp_distance, 6)
        return round(entry_price - tp_distance, 6)

    def record_result(self, won: bool) -> None:
        """Record a trade result for win rate tracking."""
        self._signal_count += 1
        if won:
            self._win_count += 1
        else:
            self._loss_count += 1

    @property
    def win_rate(self) -> float:
        """Calculate win rate percentage."""
        total = self._win_count + self._loss_count
        if total == 0:
            return 0.0
        return round((self._win_count / total) * 100, 1)

    @property
    def total_signals(self) -> int:
        return self._signal_count

    def get_status(self) -> dict:
        """Get strategy status for dashboard."""
        return {
            "name": self.name,
            "timeframe": self.timeframe,
            "enabled": self.enabled,
            "signals_generated": self._signal_count,
            "wins": self._win_count,
            "losses": self._loss_count,
            "win_rate": self.win_rate,
        }
