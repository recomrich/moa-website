"""Market regime detection - identifies trending vs ranging conditions."""

from __future__ import annotations

from enum import Enum

import pandas as pd
from loguru import logger

from indicators.trend import ema
from indicators.volatility import atr, bollinger_bands
from indicators.momentum import rsi


class MarketRegime(str, Enum):
    """Market regime types."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"


class RegimeDetector:
    """Detects current market regime to select appropriate strategies."""

    def __init__(self, lookback: int = 50) -> None:
        self._lookback = lookback
        self._current_regimes: dict[str, MarketRegime] = {}

    def detect(self, df: pd.DataFrame, symbol: str = "") -> MarketRegime:
        """Detect the current market regime.

        Uses ADX-like trend strength + volatility analysis.
        """
        if len(df) < self._lookback + 10:
            return MarketRegime.RANGING

        data = df.copy()

        # EMA alignment for trend detection
        ema_20 = ema(df, 20)
        ema_50 = ema(df, 50)
        ema_200 = ema(df, 200) if len(df) >= 210 else ema(df, 50)

        # Bollinger Band width for volatility
        bb = bollinger_bands(df)
        bb_width = (bb["BB_Upper"] - bb["BB_Lower"]) / bb["BB_Middle"]

        # ATR for volatility
        atr_values = atr(df)

        latest_20 = ema_20.iloc[-1] if not ema_20.empty else 0
        latest_50 = ema_50.iloc[-1] if not ema_50.empty else 0
        latest_200 = ema_200.iloc[-1] if not ema_200.empty else 0
        latest_bb_width = bb_width.iloc[-1] if not bb_width.empty else 0

        if pd.isna(latest_20) or pd.isna(latest_50):
            return MarketRegime.RANGING

        # Trend strength: check EMA alignment over recent bars
        recent_ema20 = ema_20.iloc[-10:]
        recent_ema50 = ema_50.iloc[-10:]
        bullish_count = sum(
            1 for a, b in zip(recent_ema20, recent_ema50)
            if not pd.isna(a) and not pd.isna(b) and a > b
        )

        # High volatility check
        if not pd.isna(latest_bb_width) and latest_bb_width > 0.08:
            regime = MarketRegime.VOLATILE
        # Strong uptrend: EMA20 > EMA50 consistently
        elif bullish_count >= 8 and latest_20 > latest_50:
            if not pd.isna(latest_200) and latest_50 > latest_200:
                regime = MarketRegime.TRENDING_UP
            else:
                regime = MarketRegime.TRENDING_UP
        # Strong downtrend
        elif bullish_count <= 2 and latest_20 < latest_50:
            regime = MarketRegime.TRENDING_DOWN
        # Ranging
        else:
            regime = MarketRegime.RANGING

        if symbol:
            prev = self._current_regimes.get(symbol)
            if prev != regime:
                logger.info(f"[REGIME] {symbol}: {prev} -> {regime.value}")
            self._current_regimes[symbol] = regime

        return regime

    def get_regime(self, symbol: str) -> MarketRegime:
        """Get last detected regime for a symbol."""
        return self._current_regimes.get(symbol, MarketRegime.RANGING)

    def get_recommended_strategies(self, regime: MarketRegime) -> list[str]:
        """Get recommended strategies for a market regime."""
        recommendations = {
            MarketRegime.TRENDING_UP: ["trend_following", "breakout", "swing_range"],
            MarketRegime.TRENDING_DOWN: ["trend_following", "mean_reversion", "swing_range"],
            MarketRegime.RANGING: ["mean_reversion", "grid_trading", "scalping", "swing_range"],
            MarketRegime.VOLATILE: ["mean_reversion", "scalping", "swing_range"],
        }
        return recommendations.get(regime, [])
