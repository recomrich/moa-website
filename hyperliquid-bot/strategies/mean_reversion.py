"""Mean Reversion strategy - RSI + Bollinger Bands."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.momentum import rsi
from indicators.volatility import bollinger_bands
from strategies.base_strategy import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion using RSI and Bollinger Bands.

    BUY:  RSI < 30 + price below lower Bollinger Band
    SELL: RSI > 70 + price above upper Bollinger Band
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "15m")
        super().__init__("mean_reversion", timeframe, params)
        self._rsi_oversold = params.get("rsi_oversold", 30)
        self._rsi_overbought = params.get("rsi_overbought", 70)
        self._bb_period = params.get("bb_period", 20)
        self._bb_std = params.get("bb_std", 2.0)

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate signal based on mean reversion conditions."""
        if len(df) < self._bb_period + 10:
            return Signal.HOLD

        data = df.copy()
        data["RSI"] = rsi(df)
        bb = bollinger_bands(df, self._bb_period, self._bb_std)
        data["BB_Upper"] = bb["BB_Upper"]
        data["BB_Lower"] = bb["BB_Lower"]

        latest = data.iloc[-1]
        current_rsi = latest.get("RSI")
        current_close = latest.get("close")
        bb_lower = latest.get("BB_Lower")
        bb_upper = latest.get("BB_Upper")

        if any(pd.isna(v) for v in [current_rsi, current_close, bb_lower, bb_upper]):
            return Signal.HOLD

        # BUY: Oversold + below lower band
        if current_rsi < self._rsi_oversold and current_close < bb_lower:
            self._signal_count += 1
            logger.info(
                f"[{self.name}] BUY signal - "
                f"RSI={current_rsi:.1f} < {self._rsi_oversold}, "
                f"price={current_close:.2f} < BB_Lower={bb_lower:.2f}"
            )
            return Signal.BUY

        # SELL: Overbought + above upper band
        if current_rsi > self._rsi_overbought and current_close > bb_upper:
            self._signal_count += 1
            logger.info(
                f"[{self.name}] SELL signal - "
                f"RSI={current_rsi:.1f} > {self._rsi_overbought}, "
                f"price={current_close:.2f} > BB_Upper={bb_upper:.2f}"
            )
            return Signal.SELL

        return Signal.HOLD
