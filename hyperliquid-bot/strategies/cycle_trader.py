"""Cycle Trader strategy - exploits recurring multi-day price oscillations.

These cryptos (ETH, SOL, PEPE, IO, etc.) fluctuate ~5% up/down almost every
day in a predictable pattern. This strategy:
1. Analyzes the last 30 days to find the recurring price range
2. Opens LONG at the bottom of the range (price dropped = buy zone)
3. Opens SHORT at the top of the range (price pumped = sell zone)
4. Multiple entries at different levels within each zone
5. Uses leverage proportional to how extreme the price position is
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.momentum import rsi
from indicators.volatility import atr
from strategies.base_strategy import BaseStrategy, Signal


class CycleTraderStrategy(BaseStrategy):
    """Cycle trading: LONG at lows, SHORT at highs of recurring oscillation.

    Analyzes 30 days of data to identify:
    - 30-day price range (support to resistance)
    - Average daily swing amplitude
    - Current position within that range

    BUY (LONG):  price in bottom 30% of 30-day range, RSI < 50, dropping
    SELL (SHORT): price in top 30% of 30-day range, RSI > 50, rising

    The bot opens multiple positions because:
    - If price stays in buy zone after cooldown (10min), another BUY triggers
    - Position manager allows up to 3 per symbol
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "15m")
        super().__init__("cycle_trader", timeframe, params)
        self._lookback_days = params.get("lookback_days", 30)
        self._buy_zone_pct = params.get("buy_zone_pct", 30)
        self._sell_zone_pct = params.get("sell_zone_pct", 30)
        self._min_range_pct = params.get("min_range_pct", 8.0)
        self._rsi_buy_max = params.get("rsi_buy_max", 50)
        self._rsi_sell_min = params.get("rsi_sell_min", 50)

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate cycle trading signal."""
        if len(df) < 96:  # need at least 1 day of 15m candles
            return Signal.HOLD

        # Build daily OHLC from intraday data
        daily = self._build_daily(df)
        if daily is None or len(daily) < 5:
            return Signal.HOLD

        # 30-day range analysis
        lookback = daily.iloc[-self._lookback_days:] if len(daily) >= self._lookback_days else daily
        range_high = float(lookback["high"].max())
        range_low = float(lookback["low"].min())
        total_range = range_high - range_low

        if total_range <= 0 or range_low <= 0:
            return Signal.HOLD

        # Check range is significant (at least min_range_pct of price)
        range_pct = (total_range / range_low) * 100
        if range_pct < self._min_range_pct:
            return Signal.HOLD

        current_close = float(df["close"].iloc[-1])

        # Where is price in the 30-day range? 0% = at low, 100% = at high
        position_pct = ((current_close - range_low) / total_range) * 100
        position_pct = max(0, min(100, position_pct))

        # RSI
        rsi_vals = rsi(df)
        current_rsi = float(rsi_vals.iloc[-1]) if not rsi_vals.empty else 50
        if pd.isna(current_rsi):
            current_rsi = 50

        # Recent price direction (last 2 hours = 8 candles on 15m)
        candles_back = min(8, len(df) - 1)
        past_close = float(df["close"].iloc[-candles_back - 1])
        recent_move_pct = ((current_close - past_close) / past_close) * 100

        # Daily direction (compare to yesterday's close)
        if len(daily) >= 2:
            yesterday_close = float(daily["close"].iloc[-2])
            daily_move_pct = ((current_close - yesterday_close) / yesterday_close) * 100
        else:
            daily_move_pct = 0

        # Average daily return amplitude (measures oscillation consistency)
        if len(daily) >= 5:
            daily["daily_return"] = daily["close"].pct_change() * 100
            avg_amplitude = float(daily["daily_return"].abs().mean())
            alternation_score = self._calc_alternation(daily)
        else:
            avg_amplitude = 0
            alternation_score = 0

        # === BUY ZONE (LONG) ===
        # Price in bottom X% of 30-day range + RSI not overbought + price was dropping
        if position_pct <= self._buy_zone_pct:
            if current_rsi < self._rsi_buy_max and recent_move_pct <= 0.5:
                self._signal_count += 1
                logger.info(
                    f"[{self.name}] BUY (LONG) - "
                    f"price at {position_pct:.0f}% of 30-day range "
                    f"[${range_low:.2f} - ${range_high:.2f}], "
                    f"RSI={current_rsi:.1f}, "
                    f"daily avg amplitude={avg_amplitude:.1f}%, "
                    f"alternation={alternation_score:.0f}%"
                )
                return Signal.BUY

        # === SELL ZONE (SHORT) ===
        # Price in top X% of 30-day range + RSI not oversold + price was rising
        if position_pct >= (100 - self._sell_zone_pct):
            if current_rsi > self._rsi_sell_min and recent_move_pct >= -0.5:
                self._signal_count += 1
                logger.info(
                    f"[{self.name}] SELL (SHORT) - "
                    f"price at {position_pct:.0f}% of 30-day range "
                    f"[${range_low:.2f} - ${range_high:.2f}], "
                    f"RSI={current_rsi:.1f}, "
                    f"daily avg amplitude={avg_amplitude:.1f}%, "
                    f"alternation={alternation_score:.0f}%"
                )
                return Signal.SELL

        return Signal.HOLD

    def _calc_alternation(self, daily: pd.DataFrame) -> float:
        """Calculate how often the price alternates direction (up day followed by down day).

        Returns 0-100%: higher = more consistent oscillation = better for this strategy.
        """
        if "daily_return" not in daily.columns or len(daily) < 5:
            return 0

        returns = daily["daily_return"].dropna().values
        if len(returns) < 4:
            return 0

        alternations = 0
        for i in range(1, len(returns)):
            # Count sign changes (positive day followed by negative, or vice versa)
            if returns[i] * returns[i - 1] < 0:
                alternations += 1

        return (alternations / (len(returns) - 1)) * 100

    def _build_daily(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Build daily OHLC from intraday data."""
        try:
            data = df.copy()

            if "timestamp" in data.columns:
                data["date"] = pd.to_datetime(data["timestamp"], unit="ms").dt.date
            elif hasattr(data.index, "date"):
                data["date"] = data.index.date
            else:
                bars_per_day = 96 if self.timeframe == "15m" else (288 if self.timeframe == "5m" else 24)
                if len(data) < bars_per_day * 3:
                    return None
                data["date"] = [i // bars_per_day for i in range(len(data))]

            daily = data.groupby("date").agg(
                high=("high", "max"),
                low=("low", "min"),
                open=("open", "first"),
                close=("close", "last"),
            )

            return daily if len(daily) >= 3 else None

        except Exception as e:
            logger.debug(f"Daily OHLC build error: {e}")
            return None

    def get_stop_loss(
        self, entry_price: float, atr_value: float, side: str = "buy"
    ) -> float:
        """SL based on ATR. Tighter for cycle trades (1.2x ATR)."""
        mult = 1.2
        if side == "buy":
            return round(entry_price - (atr_value * mult), 6)
        return round(entry_price + (atr_value * mult), 6)

    def get_take_profit(
        self, entry_price: float, atr_value: float,
        side: str = "buy", ratio: float = 2.0
    ) -> float:
        """TP at 2.5x ATR for cycle trades (R:R = ~2.0)."""
        mult = 2.5
        if side == "buy":
            return round(entry_price + (atr_value * mult), 6)
        return round(entry_price - (atr_value * mult), 6)
