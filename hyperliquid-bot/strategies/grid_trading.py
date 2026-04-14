"""Grid Trading strategy - profit from price oscillations in a range."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.volatility import atr, bollinger_bands
from strategies.base_strategy import BaseStrategy, Signal


class GridTradingStrategy(BaseStrategy):
    """Grid trading within a price range.

    Places virtual buy/sell levels based on Bollinger Bands.
    BUY:  Price drops to lower grid levels
    SELL: Price rises to upper grid levels
    Best in ranging/sideways markets.
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "15m")
        super().__init__("grid_trading", timeframe, params)
        self._grid_levels = params.get("grid_levels", 5)
        self._bb_period = params.get("bb_period", 20)
        self._bb_std = params.get("bb_std", 2.0)

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate signal based on grid position within Bollinger Bands."""
        if len(df) < self._bb_period + 10:
            return Signal.HOLD

        bb = bollinger_bands(df, self._bb_period, self._bb_std)
        latest_close = df["close"].iloc[-1]
        bb_upper = bb["BB_Upper"].iloc[-1]
        bb_lower = bb["BB_Lower"].iloc[-1]
        bb_middle = bb["BB_Middle"].iloc[-1]

        if any(pd.isna(v) for v in [bb_upper, bb_lower, bb_middle, latest_close]):
            return Signal.HOLD

        band_range = bb_upper - bb_lower
        if band_range <= 0:
            return Signal.HOLD

        # Position in the band (0 = lower, 1 = upper)
        position_in_band = (latest_close - bb_lower) / band_range

        # Previous position for detecting movement direction
        prev_close = df["close"].iloc[-2]
        prev_upper = bb["BB_Upper"].iloc[-2]
        prev_lower = bb["BB_Lower"].iloc[-2]
        if not pd.isna(prev_upper) and not pd.isna(prev_lower):
            prev_range = prev_upper - prev_lower
            if prev_range > 0:
                prev_position = (prev_close - prev_lower) / prev_range
            else:
                prev_position = 0.5
        else:
            prev_position = 0.5

        # BUY: Price in lower 20% of band and moving down (bounce expected)
        if position_in_band < 0.2 and prev_position > position_in_band:
            self._signal_count += 1
            logger.info(
                f"[{self.name}] BUY signal - "
                f"price at {position_in_band:.1%} of BB range (lower zone)"
            )
            return Signal.BUY

        # SELL: Price in upper 80% of band and moving up (reversal expected)
        if position_in_band > 0.8 and prev_position < position_in_band:
            self._signal_count += 1
            logger.info(
                f"[{self.name}] SELL signal - "
                f"price at {position_in_band:.1%} of BB range (upper zone)"
            )
            return Signal.SELL

        return Signal.HOLD

    def get_stop_loss(
        self, entry_price: float, atr_value: float, side: str = "buy"
    ) -> float:
        """Tighter stop for grid trading (1x ATR)."""
        if side == "buy":
            return round(entry_price - atr_value, 6)
        return round(entry_price + atr_value, 6)

    def get_take_profit(
        self, entry_price: float, atr_value: float,
        side: str = "buy", ratio: float = 1.5
    ) -> float:
        """Closer take-profit for grid trading (1.5x ATR)."""
        if side == "buy":
            return round(entry_price + (atr_value * ratio), 6)
        return round(entry_price - (atr_value * ratio), 6)
