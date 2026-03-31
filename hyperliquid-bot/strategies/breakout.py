"""Breakout strategy - price breakout with volume confirmation."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.volatility import atr
from indicators.volume import volume_sma
from strategies.base_strategy import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    """Breakout detection with volume confirmation.

    BUY:  Price breaks above resistance + volume > avg * multiplier
    SELL: Price breaks below support + volume > avg * multiplier
    Stop-loss: ATR * 1.5 below breakout point
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "1h")
        super().__init__("breakout", timeframe, params)
        self._volume_multiplier = params.get("volume_multiplier", 1.5)
        self._lookback = params.get("lookback_period", 20)

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate signal based on breakout conditions."""
        if len(df) < self._lookback + 5:
            return Signal.HOLD

        data = df.copy()
        data["ATR"] = atr(df)
        data["Volume_SMA"] = volume_sma(df, self._lookback)

        latest = data.iloc[-1]
        current_close = latest.get("close")
        current_volume = latest.get("volume", 0)
        avg_volume = latest.get("Volume_SMA")
        current_atr = latest.get("ATR")

        if any(pd.isna(v) for v in [current_close, avg_volume, current_atr]):
            return Signal.HOLD

        # Calculate resistance and support from lookback period
        lookback_data = data.iloc[-(self._lookback + 1):-1]
        resistance = lookback_data["high"].max()
        support = lookback_data["low"].min()

        # Volume confirmation threshold
        volume_threshold = avg_volume * self._volume_multiplier
        high_volume = current_volume > volume_threshold

        # BUY: Breakout above resistance with volume
        if current_close > resistance and high_volume:
            self._signal_count += 1
            logger.info(
                f"[{self.name}] BUY signal - "
                f"breakout above {resistance:.2f}, "
                f"volume={current_volume:.0f} > threshold={volume_threshold:.0f}"
            )
            return Signal.BUY

        # SELL: Breakdown below support with volume
        if current_close < support and high_volume:
            self._signal_count += 1
            logger.info(
                f"[{self.name}] SELL signal - "
                f"breakdown below {support:.2f}, "
                f"volume={current_volume:.0f} > threshold={volume_threshold:.0f}"
            )
            return Signal.SELL

        return Signal.HOLD

    def get_stop_loss(
        self, entry_price: float, atr_value: float, side: str = "buy"
    ) -> float:
        """ATR * 1.5 stop-loss for breakout trades."""
        if side == "buy":
            return round(entry_price - (atr_value * 1.5), 6)
        return round(entry_price + (atr_value * 1.5), 6)
