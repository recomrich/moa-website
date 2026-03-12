"""
Stratégie Mean Reversion — retour à la moyenne RSI + Bollinger Bands.

Signal BUY  : RSI < 30 + prix sous Bollinger Band inférieure
Signal SELL : RSI > 70 + prix au-dessus Bollinger Band supérieure
Timeframe   : 15m (configurable)
"""

import math

import pandas as pd
from loguru import logger

from indicators.momentum import add_rsi, get_rsi_zone
from indicators.volatility import add_atr, add_bollinger_bands, get_bb_position, get_current_atr
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal

MIN_CANDLES = 50


class MeanReversionStrategy(BaseStrategy):
    """
    Stratégie de retour à la moyenne combinant RSI et Bollinger Bands.

    Identifie les zones d'extrême sur-achat / sur-vente avec double confirmation.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialise la stratégie Mean Reversion.

        Args:
            config: Configuration (rsi_period, rsi_oversold, rsi_overbought, bb_*).
        """
        timeframe = config.get("timeframe", "15m")
        super().__init__("mean_reversion", config, timeframe)

        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_oversold = config.get("rsi_oversold", 30)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 2.0)
        self.atr_period = 14

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute RSI, Bollinger Bands et ATR au DataFrame."""
        df = add_rsi(df, self.rsi_period)
        df = add_bollinger_bands(df, self.bb_period, self.bb_std)
        df = add_atr(df, self.atr_period)
        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        current_price: float,
    ) -> TradeSignal:
        """
        Génère un signal basé sur RSI et Bollinger Bands.

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

        rsi_col = f"rsi_{self.rsi_period}"
        rsi_val = last.get(rsi_col)
        bb_upper = last.get("bb_upper")
        bb_middle = last.get("bb_middle")
        bb_lower = last.get("bb_lower")
        atr_value = get_current_atr(df, self.atr_period)

        if any(v is None or math.isnan(float(v)) for v in [rsi_val, bb_upper, bb_middle, bb_lower]):
            return self._hold_signal(symbol, current_price, "Indicateurs non disponibles")

        rsi_val = float(rsi_val)
        bb_upper = float(bb_upper)
        bb_middle = float(bb_middle)
        bb_lower = float(bb_lower)

        rsi_zone = get_rsi_zone(rsi_val, self.rsi_oversold, self.rsi_overbought)
        bb_pos = get_bb_position(current_price, bb_upper, bb_middle, bb_lower)

        if atr_value <= 0:
            return self._hold_signal(symbol, current_price, "ATR invalide")

        # Signal BUY : sur-vente RSI + prix sous BB inférieure
        if rsi_zone == "oversold" and bb_pos == "below_lower":
            sl = self.get_stop_loss(current_price, atr_value, is_long=True)
            tp = bb_middle  # TP = retour à la moyenne BB

            if (tp - current_price) / abs(current_price - sl) < 1.5:
                tp = self.get_take_profit(current_price, atr_value, is_long=True)

            signal = TradeSignal(
                signal=Signal.BUY,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=0.75,
                timeframe=self.timeframe,
                reason=f"RSI sur-vente ({rsi_val:.1f}) + prix sous BB inférieure",
            )
            self.record_signal(signal)
            logger.info(
                f"[{self.name}] BUY {symbol} @ {current_price:.4f} | "
                f"RSI: {rsi_val:.1f} | SL: {sl:.4f} | TP: {tp:.4f}"
            )
            return signal

        # Signal SELL : sur-achat RSI + prix au-dessus BB supérieure
        if rsi_zone == "overbought" and bb_pos == "above_upper":
            sl = self.get_stop_loss(current_price, atr_value, is_long=False)
            tp = bb_middle  # TP = retour à la moyenne BB

            if (current_price - tp) / abs(sl - current_price) < 1.5:
                tp = self.get_take_profit(current_price, atr_value, is_long=False)

            signal = TradeSignal(
                signal=Signal.SELL,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=0.75,
                timeframe=self.timeframe,
                reason=f"RSI sur-achat ({rsi_val:.1f}) + prix au-dessus BB supérieure",
            )
            self.record_signal(signal)
            logger.info(
                f"[{self.name}] SELL {symbol} @ {current_price:.4f} | "
                f"RSI: {rsi_val:.1f} | SL: {sl:.4f} | TP: {tp:.4f}"
            )
            return signal

        return self._hold_signal(
            symbol, current_price,
            f"Pas de signal — RSI: {rsi_val:.1f} ({rsi_zone}), BB: {bb_pos}"
        )
