"""Scalping strategy - fast EMA crossovers + RSI filter."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.momentum import rsi
from indicators.trend import ema
from strategies.base_strategy import BaseStrategy, Signal


class ScalpingStrategy(BaseStrategy):
    """Scalping with short EMA crossovers and RSI filter.

    BUY:  EMA5 > EMA13 + RSI between 45-65
    SELL: EMA5 < EMA13 + RSI between 35-55
    Short positions, TP 0.5-1%, SL 0.3%
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "5m")
        super().__init__("scalping", timeframe, params)
        self._ema_fast = params.get("ema_fast", 5)
        self._ema_slow = params.get("ema_slow", 13)
        self._tp_pct = params.get("tp_pct", 0.5)
        self._sl_pct = params.get("sl_pct", 0.3)

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate scalping signal."""
        if len(df) < self._ema_slow + 5:
            return Signal.HOLD

        data = df.copy()
        data["EMA_fast"] = ema(df, self._ema_fast)
        data["EMA_slow"] = ema(df, self._ema_slow)
        data["RSI"] = rsi(df)

        latest = data.iloc[-1]
        prev = data.iloc[-2]

        ema_fast_val = latest.get("EMA_fast")
        ema_slow_val = latest.get("EMA_slow")
        rsi_val = latest.get("RSI")

        if any(pd.isna(v) for v in [ema_fast_val, ema_slow_val, rsi_val]):
            return Signal.HOLD

        prev_fast = prev.get("EMA_fast")
        prev_slow = prev.get("EMA_slow")

        if pd.isna(prev_fast) or pd.isna(prev_slow):
            return Signal.HOLD

        # BUY: Fast EMA crosses above slow + RSI in neutral-bullish zone
        if (
            ema_fast_val > ema_slow_val
            and prev_fast <= prev_slow
            and 45 <= rsi_val <= 65
        ):
            self._signal_count += 1
            logger.info(
                f"[{self.name}] BUY signal - "
                f"EMA{self._ema_fast} crossed above EMA{self._ema_slow}, "
                f"RSI={rsi_val:.1f}"
            )
            return Signal.BUY

        # SELL: Fast EMA crosses below slow + RSI in neutral-bearish zone
        if (
            ema_fast_val < ema_slow_val
            and prev_fast >= prev_slow
            and 35 <= rsi_val <= 55
        ):
            self._signal_count += 1
            logger.info(
                f"[{self.name}] SELL signal - "
                f"EMA{self._ema_fast} crossed below EMA{self._ema_slow}, "
                f"RSI={rsi_val:.1f}"
            )
            return Signal.SELL

        return Signal.HOLD

    def get_stop_loss(
        self, entry_price: float, atr_value: float = 0, side: str = "buy"
    ) -> float:
        """Fixed percentage stop-loss for scalping."""
        pct = self._sl_pct / 100
        if side == "buy":
            return round(entry_price * (1 - pct), 6)
        return round(entry_price * (1 + pct), 6)

    def get_take_profit(
        self, entry_price: float, atr_value: float = 0,
        side: str = "buy", ratio: float = 2.0
    ) -> float:
        """Fixed percentage take-profit for scalping."""
        pct = self._tp_pct / 100
        if side == "buy":
            return round(entry_price * (1 + pct), 6)
        return round(entry_price * (1 - pct), 6)
