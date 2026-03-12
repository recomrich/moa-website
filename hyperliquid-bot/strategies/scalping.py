"""
Stratégie Scalping — positions courtes sur petits timeframes.

Signal BUY  : EMA5 > EMA13 + RSI entre 45-65
Signal SELL : EMA5 < EMA13 + RSI entre 35-55
Timeframe   : 5m (configurable)
"""

import math

import pandas as pd
from loguru import logger

from indicators.momentum import add_rsi
from indicators.trend import add_ema_indicators
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal

MIN_CANDLES = 30


class ScalpingStrategy(BaseStrategy):
    """
    Stratégie de scalping sur petits timeframes.

    Exploite les micro-tendances avec des entrées précises et
    des objectifs limités (0.5-1%) pour un ratio trades/jour élevé.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialise la stratégie Scalping.

        Args:
            config: Configuration (ema_fast, ema_slow, rsi_min, rsi_max, tp_pct, sl_pct).
        """
        timeframe = config.get("timeframe", "5m")
        super().__init__("scalping", config, timeframe)

        self.ema_fast = config.get("ema_fast", 5)
        self.ema_slow = config.get("ema_slow", 13)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_min = config.get("rsi_min", 45)
        self.rsi_max = config.get("rsi_max", 65)
        self.tp_pct = config.get("tp_pct", 0.8) / 100
        self.sl_pct = config.get("sl_pct", 0.3) / 100

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute EMA courtes et RSI au DataFrame."""
        df = add_ema_indicators(df, [self.ema_fast, self.ema_slow])
        df = add_rsi(df, self.rsi_period)
        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        current_price: float,
    ) -> TradeSignal:
        """
        Génère un signal de scalping.

        Args:
            df: DataFrame OHLCV préparé.
            symbol: Symbole de l'actif.
            current_price: Prix courant.

        Returns:
            TradeSignal avec BUY, SELL ou HOLD.
        """
        if len(df) < MIN_CANDLES:
            return self._hold_signal(symbol, current_price, "Données insuffisantes")

        last = df.iloc[-1]

        ema_fast_col = f"ema_{self.ema_fast}"
        ema_slow_col = f"ema_{self.ema_slow}"
        rsi_col = f"rsi_{self.rsi_period}"

        ema_f = last.get(ema_fast_col)
        ema_s = last.get(ema_slow_col)
        rsi_val = last.get(rsi_col)

        if any(v is None or math.isnan(float(v)) for v in [ema_f, ema_s, rsi_val]):
            return self._hold_signal(symbol, current_price, "Indicateurs non disponibles")

        ema_f = float(ema_f)
        ema_s = float(ema_s)
        rsi_val = float(rsi_val)

        ema_bullish = ema_f > ema_s
        ema_bearish = ema_f < ema_s
        rsi_in_buy_zone = self.rsi_min <= rsi_val <= self.rsi_max
        rsi_in_sell_zone = (100 - self.rsi_max) <= rsi_val <= (100 - self.rsi_min)

        # Signal BUY : EMA5 > EMA13 + RSI en zone neutre-haussière
        if ema_bullish and rsi_in_buy_zone:
            tp = current_price * (1 + self.tp_pct)
            sl = current_price * (1 - self.sl_pct)

            signal = TradeSignal(
                signal=Signal.BUY,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=0.65,
                timeframe=self.timeframe,
                reason=(
                    f"EMA{self.ema_fast} > EMA{self.ema_slow} + RSI {rsi_val:.1f} "
                    f"en zone [{self.rsi_min}-{self.rsi_max}]"
                ),
            )
            self.record_signal(signal)
            logger.debug(
                f"[{self.name}] BUY {symbol} @ {current_price:.4f} | "
                f"RSI: {rsi_val:.1f} | TP: {tp:.4f} | SL: {sl:.4f}"
            )
            return signal

        # Signal SELL : EMA5 < EMA13 + RSI en zone neutre-baissière
        if ema_bearish and rsi_in_sell_zone:
            tp = current_price * (1 - self.tp_pct)
            sl = current_price * (1 + self.sl_pct)

            signal = TradeSignal(
                signal=Signal.SELL,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=0.65,
                timeframe=self.timeframe,
                reason=(
                    f"EMA{self.ema_fast} < EMA{self.ema_slow} + RSI {rsi_val:.1f} "
                    f"en zone [{100-self.rsi_max}-{100-self.rsi_min}]"
                ),
            )
            self.record_signal(signal)
            logger.debug(
                f"[{self.name}] SELL {symbol} @ {current_price:.4f} | "
                f"RSI: {rsi_val:.1f} | TP: {tp:.4f} | SL: {sl:.4f}"
            )
            return signal

        return self._hold_signal(
            symbol, current_price,
            f"Pas de signal — EMA: {'bull' if ema_bullish else 'bear'} | RSI: {rsi_val:.1f}"
        )
