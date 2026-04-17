"""Momentum strategy - catches strong directional price moves (+3-8% daily).

Designed to enter early in a pump/dump by detecting:
- Price moving strongly in one direction over recent candles
- RSI in momentum zone (not overbought/oversold yet)
- Volume confirming the move
- Fast EMAs aligned
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from indicators.momentum import rsi
from indicators.trend import ema
from indicators.volume import volume_sma
from strategies.base_strategy import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    """Catches strong directional momentum before it becomes overbought.

    BUY:  EMA9 > EMA21, price +1.5%+ over last 4 candles, RSI 48-72
    SELL: EMA9 < EMA21, price -1.5%+ over last 4 candles, RSI 28-52
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "15m")
        super().__init__("momentum", timeframe, params)
        self._ema_fast = params.get("ema_fast", 9)
        self._ema_slow = params.get("ema_slow", 21)
        self._momentum_pct = params.get("momentum_pct", 1.5)   # % move required
        self._rsi_min_buy = params.get("rsi_min_buy", 48)
        self._rsi_max_buy = params.get("rsi_max_buy", 72)
        self._rsi_min_sell = params.get("rsi_min_sell", 28)
        self._rsi_max_sell = params.get("rsi_max_sell", 52)
        self._lookback_candles = params.get("lookback_candles", 4)  # candles to measure move

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate momentum signal."""
        if len(df) < self._ema_slow + 10:
            return Signal.HOLD

        fast_ema = ema(df, self._ema_fast)
        slow_ema = ema(df, self._ema_slow)
        rsi_vals = rsi(df)

        if fast_ema.empty or slow_ema.empty or rsi_vals.empty:
            return Signal.HOLD

        ema_fast_val = fast_ema.iloc[-1]
        ema_slow_val = slow_ema.iloc[-1]
        current_rsi = float(rsi_vals.iloc[-1])
        current_close = float(df["close"].iloc[-1])

        if any(pd.isna(v) for v in [ema_fast_val, ema_slow_val, current_rsi]):
            return Signal.HOLD

        # Calculate price momentum over last N candles
        lookback_idx = max(0, len(df) - self._lookback_candles - 1)
        past_close = float(df["close"].iloc[lookback_idx])
        if past_close == 0:
            return Signal.HOLD

        momentum_pct = ((current_close - past_close) / past_close) * 100

        # Volume check: current volume vs recent average
        recent_vol = df["volume"].iloc[-self._lookback_candles:].mean()
        current_vol = float(df["volume"].iloc[-1])
        vol_ok = current_vol >= recent_vol * 0.8  # soft volume check

        # BUY: strong upward momentum + EMAs aligned bullish + RSI not overbought
        if (
            momentum_pct >= self._momentum_pct
            and ema_fast_val > ema_slow_val
            and self._rsi_min_buy <= current_rsi <= self._rsi_max_buy
            and vol_ok
        ):
            self._signal_count += 1
            logger.info(
                f"[{self.name}] BUY signal - "
                f"momentum={momentum_pct:.2f}% over {self._lookback_candles} candles, "
                f"RSI={current_rsi:.1f}, EMA9={ema_fast_val:.2f} > EMA21={ema_slow_val:.2f}"
            )
            return Signal.BUY

        # SELL: strong downward momentum + EMAs aligned bearish + RSI not oversold
        if (
            momentum_pct <= -self._momentum_pct
            and ema_fast_val < ema_slow_val
            and self._rsi_min_sell <= current_rsi <= self._rsi_max_sell
            and vol_ok
        ):
            self._signal_count += 1
            logger.info(
                f"[{self.name}] SELL signal - "
                f"momentum={momentum_pct:.2f}% over {self._lookback_candles} candles, "
                f"RSI={current_rsi:.1f}, EMA9={ema_fast_val:.2f} < EMA21={ema_slow_val:.2f}"
            )
            return Signal.SELL

        return Signal.HOLD

    def get_stop_loss(
        self, entry_price: float, atr_value: float, side: str = "buy"
    ) -> float:
        """1.5x ATR stop for momentum trades."""
        if side == "buy":
            return round(entry_price - (atr_value * 1.5), 6)
        return round(entry_price + (atr_value * 1.5), 6)

    def get_take_profit(
        self, entry_price: float, atr_value: float,
        side: str = "buy", ratio: float = 2.0
    ) -> float:
        """3x ATR target for momentum trades (R:R = 2.0)."""
        if side == "buy":
            return round(entry_price + (atr_value * 3.0), 6)
        return round(entry_price - (atr_value * 3.0), 6)
