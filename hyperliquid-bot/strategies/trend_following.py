"""Trend Following strategy - EMA crossovers + MACD confirmation."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.trend import add_trend_indicators
from strategies.base_strategy import BaseStrategy, Signal


class TrendFollowingStrategy(BaseStrategy):
    """Trend following using EMA 20/50/200 and MACD.

    BUY:  EMA20 > EMA50 > EMA200 + MACD > Signal line
    SELL: EMA20 < EMA50 + MACD < Signal line
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "1h")
        super().__init__("trend_following", timeframe, params)
        self._ema_periods = params.get("ema_periods", [20, 50, 200])

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate trading signal based on trend alignment."""
        if len(df) < max(self._ema_periods) + 10:
            return Signal.HOLD

        data = add_trend_indicators(df, self._ema_periods)

        latest = data.iloc[-1]
        prev = data.iloc[-2]

        ema_20 = latest.get("EMA_20")
        ema_50 = latest.get("EMA_50")
        ema_200 = latest.get("EMA_200")
        macd_val = latest.get("MACD")
        macd_signal = latest.get("MACD_Signal")

        if any(pd.isna(v) for v in [ema_20, ema_50, ema_200, macd_val, macd_signal]):
            return Signal.HOLD

        # BUY: Bullish trend alignment + MACD confirmation
        if ema_20 > ema_50 > ema_200 and macd_val > macd_signal:
            # Confirm MACD just crossed above signal (fresh signal)
            prev_macd = prev.get("MACD", 0)
            prev_signal = prev.get("MACD_Signal", 0)
            if not pd.isna(prev_macd) and not pd.isna(prev_signal):
                if prev_macd <= prev_signal:
                    self._signal_count += 1
                    logger.info(
                        f"[{self.name}] BUY signal - "
                        f"EMA20={ema_20:.2f} > EMA50={ema_50:.2f} > "
                        f"EMA200={ema_200:.2f}, MACD crossover"
                    )
                    return Signal.BUY

        # SELL: Bearish alignment + MACD confirmation
        if ema_20 < ema_50 and macd_val < macd_signal:
            prev_macd = prev.get("MACD", 0)
            prev_signal = prev.get("MACD_Signal", 0)
            if not pd.isna(prev_macd) and not pd.isna(prev_signal):
                if prev_macd >= prev_signal:
                    self._signal_count += 1
                    logger.info(
                        f"[{self.name}] SELL signal - "
                        f"EMA20={ema_20:.2f} < EMA50={ema_50:.2f}, "
                        f"MACD cross below"
                    )
                    return Signal.SELL

        return Signal.HOLD
