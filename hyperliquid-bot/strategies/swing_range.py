"""Swing Range strategy - exploits predictable daily price fluctuations.

Analyzes the average daily range of each asset over the last 30 days.
Buys when price drops to the lower zone of the typical daily range,
sells when it reaches the upper zone. Designed for cryptos that
consistently fluctuate 3-8% per day within a range.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.volatility import atr, bollinger_bands
from indicators.momentum import rsi
from strategies.base_strategy import BaseStrategy, Signal


class SwingRangeStrategy(BaseStrategy):
    """Swing trading based on daily range patterns.

    Calculates the average daily high-low range over the past N days.
    BUY:  Price is in the lower 25% of the typical daily range + RSI < 45
    SELL: Price is in the upper 25% of the typical daily range + RSI > 55
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "15m")
        super().__init__("swing_range", timeframe, params)
        self._lookback_days = params.get("lookback_days", 30)
        self._entry_zone_pct = params.get("entry_zone_pct", 25)
        self._min_daily_range_pct = params.get("min_daily_range_pct", 2.0)

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate signal based on position within daily range."""
        if len(df) < 50:
            return Signal.HOLD

        # Calculate daily ranges from intraday data
        daily_stats = self._calc_daily_ranges(df)
        if daily_stats is None:
            return Signal.HOLD

        avg_range_pct = daily_stats["avg_range_pct"]
        avg_high_offset = daily_stats["avg_high_offset"]
        avg_low_offset = daily_stats["avg_low_offset"]

        # Skip if daily range is too small (not enough fluctuation)
        if avg_range_pct < self._min_daily_range_pct:
            return Signal.HOLD

        # Current price info
        current_close = df["close"].iloc[-1]
        today_open = daily_stats["today_open"]
        if today_open == 0:
            return Signal.HOLD

        # Expected daily range from today's open
        expected_high = today_open * (1 + avg_high_offset)
        expected_low = today_open * (1 - abs(avg_low_offset))
        expected_range = expected_high - expected_low

        if expected_range <= 0:
            return Signal.HOLD

        # Position within expected range (0 = at low, 1 = at high)
        position_in_range = (current_close - expected_low) / expected_range
        position_in_range = max(0, min(1, position_in_range))

        # RSI for confirmation
        rsi_values = rsi(df)
        current_rsi = float(rsi_values.iloc[-1]) if not rsi_values.empty else 50
        if pd.isna(current_rsi):
            current_rsi = 50

        # Also check if price is moving (not stagnant)
        price_5_bars_ago = df["close"].iloc[-6] if len(df) > 6 else current_close
        recent_move = ((current_close - price_5_bars_ago) / price_5_bars_ago) * 100

        entry_threshold = self._entry_zone_pct / 100  # 0.25

        # BUY: Price in lower zone + RSI not overbought + price was falling
        if position_in_range < entry_threshold and current_rsi < 45:
            if recent_move < 0:  # Price was dropping (bounce expected)
                self._signal_count += 1
                logger.info(
                    f"[{self.name}] BUY signal - "
                    f"price at {position_in_range:.0%} of daily range, "
                    f"RSI={current_rsi:.1f}, "
                    f"avg daily range={avg_range_pct:.1f}%, "
                    f"expected low=${expected_low:.2f}"
                )
                return Signal.BUY

        # SELL: Price in upper zone + RSI not oversold + price was rising
        if position_in_range > (1 - entry_threshold) and current_rsi > 55:
            if recent_move > 0:  # Price was rising (drop expected)
                self._signal_count += 1
                logger.info(
                    f"[{self.name}] SELL signal - "
                    f"price at {position_in_range:.0%} of daily range, "
                    f"RSI={current_rsi:.1f}, "
                    f"avg daily range={avg_range_pct:.1f}%, "
                    f"expected high=${expected_high:.2f}"
                )
                return Signal.SELL

        return Signal.HOLD

    def _calc_daily_ranges(self, df: pd.DataFrame) -> dict | None:
        """Calculate average daily range statistics from intraday data."""
        try:
            data = df.copy()

            # Need a datetime index for grouping by day
            if "timestamp" in data.columns:
                data["date"] = pd.to_datetime(data["timestamp"], unit="ms").dt.date
            elif hasattr(data.index, "date"):
                data["date"] = data.index.date
            else:
                # Estimate days from bar count (15min = 96 bars/day)
                bars_per_day = 96 if self.timeframe == "15m" else 24
                if len(data) < bars_per_day * 3:
                    return None
                # Group by approximate days
                data["date"] = [i // bars_per_day for i in range(len(data))]

            # Daily high, low, open, close
            daily = data.groupby("date").agg(
                high=("high", "max"),
                low=("low", "min"),
                open=("open", "first"),
                close=("close", "last"),
            )

            if len(daily) < 5:
                return None

            # Calculate daily ranges
            daily["range_pct"] = ((daily["high"] - daily["low"]) / daily["low"]) * 100
            daily["high_offset"] = (daily["high"] - daily["open"]) / daily["open"]
            daily["low_offset"] = (daily["open"] - daily["low"]) / daily["open"]

            # Use last N days (exclude today which is incomplete)
            lookback = daily.iloc[-self._lookback_days - 1:-1] if len(daily) > 3 else daily.iloc[:-1]

            if lookback.empty:
                return None

            # Today's open
            today_open = float(daily.iloc[-1]["open"])

            return {
                "avg_range_pct": float(lookback["range_pct"].mean()),
                "avg_high_offset": float(lookback["high_offset"].mean()),
                "avg_low_offset": float(lookback["low_offset"].mean()),
                "range_consistency": float(lookback["range_pct"].std()),
                "today_open": today_open,
            }

        except Exception as e:
            logger.debug(f"Daily range calc error: {e}")
            return None

    def get_stop_loss(
        self, entry_price: float, atr_value: float, side: str = "buy"
    ) -> float:
        """Tight SL for range trading (1x ATR)."""
        if side == "buy":
            return round(entry_price - atr_value, 6)
        return round(entry_price + atr_value, 6)

    def get_take_profit(
        self, entry_price: float, atr_value: float,
        side: str = "buy", ratio: float = 1.5,
    ) -> float:
        """Quick TP for range trading (1.5x ATR)."""
        if side == "buy":
            return round(entry_price + (atr_value * ratio), 6)
        return round(entry_price - (atr_value * ratio), 6)
