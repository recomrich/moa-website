"""
Stratégie Trend Following — suivi de tendance EMA + MACD.

Signal BUY  : EMA20 > EMA50 > EMA200 + MACD > Signal line
Signal SELL : EMA20 < EMA50 + MACD < Signal line
Timeframe   : 1h (configurable)
"""

import pandas as pd
from loguru import logger

from indicators.trend import add_ema_indicators, add_macd, detect_ema_trend, detect_macd_crossover
from indicators.volatility import add_atr, get_current_atr
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal

MIN_CANDLES = 210  # EMA200 + marge


class TrendFollowingStrategy(BaseStrategy):
    """
    Stratégie de suivi de tendance basée sur les EMA et le MACD.

    Cherche des tendances établies avec confirmation multi-timeframe.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialise la stratégie Trend Following.

        Args:
            config: Configuration (ema_fast, ema_mid, ema_slow, macd_*).
        """
        timeframe = config.get("timeframe", "1h")
        super().__init__("trend_following", config, timeframe)

        self.ema_fast = config.get("ema_fast", 20)
        self.ema_mid = config.get("ema_mid", 50)
        self.ema_slow = config.get("ema_slow", 200)
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)
        self.atr_period = 14

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute les EMA, MACD et ATR au DataFrame."""
        df = add_ema_indicators(df, [self.ema_fast, self.ema_mid, self.ema_slow])
        df = add_macd(df, self.macd_fast, self.macd_slow, self.macd_signal)
        df = add_atr(df, self.atr_period)
        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        current_price: float,
    ) -> TradeSignal:
        """
        Génère un signal de trading basé sur les EMA et le MACD.

        Args:
            df: DataFrame OHLCV (doit être passé dans prepare_dataframe d'abord).
            symbol: Symbole de l'actif.
            current_price: Prix courant.

        Returns:
            TradeSignal avec BUY, SELL ou HOLD.
        """
        if len(df) < MIN_CANDLES:
            return self._hold_signal(symbol, current_price, "Données insuffisantes")

        trend = detect_ema_trend(df, self.ema_fast, self.ema_mid, self.ema_slow)
        macd_cross = detect_macd_crossover(df)
        atr_value = get_current_atr(df, self.atr_period)

        last = df.iloc[-1]
        macd_val = last.get("macd")
        macd_sig = last.get("macd_signal")

        import math
        macd_above_signal = (
            not math.isnan(float(macd_val or float("nan")))
            and not math.isnan(float(macd_sig or float("nan")))
            and float(macd_val) > float(macd_sig)
        )
        macd_below_signal = (
            not math.isnan(float(macd_val or float("nan")))
            and not math.isnan(float(macd_sig or float("nan")))
            and float(macd_val) < float(macd_sig)
        )

        if atr_value <= 0:
            return self._hold_signal(symbol, current_price, "ATR invalide")

        # Signal BUY : tendance haussière + MACD au-dessus de la signal line
        if trend == "bullish" and macd_above_signal:
            sl = self.get_stop_loss(current_price, atr_value, is_long=True)
            tp = self.get_take_profit(current_price, atr_value, is_long=True)

            signal = TradeSignal(
                signal=Signal.BUY,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=0.8 if macd_cross == "bullish_cross" else 0.6,
                timeframe=self.timeframe,
                reason=f"Tendance haussière EMA + MACD > Signal | Cross: {macd_cross}",
            )
            self.record_signal(signal)
            logger.info(f"[{self.name}] BUY {symbol} @ {current_price:.4f} | SL: {sl:.4f} | TP: {tp:.4f}")
            return signal

        # Signal SELL : tendance baissière + MACD sous la signal line
        if trend == "bearish" and macd_below_signal:
            sl = self.get_stop_loss(current_price, atr_value, is_long=False)
            tp = self.get_take_profit(current_price, atr_value, is_long=False)

            signal = TradeSignal(
                signal=Signal.SELL,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=0.8 if macd_cross == "bearish_cross" else 0.6,
                timeframe=self.timeframe,
                reason=f"Tendance baissière EMA + MACD < Signal | Cross: {macd_cross}",
            )
            self.record_signal(signal)
            logger.info(f"[{self.name}] SELL {symbol} @ {current_price:.4f} | SL: {sl:.4f} | TP: {tp:.4f}")
            return signal

        return self._hold_signal(
            symbol, current_price,
            f"Pas de signal — tendance: {trend}, MACD: {'above' if macd_above_signal else 'below'}"
        )
