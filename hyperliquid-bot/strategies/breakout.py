"""
Stratégie Breakout — cassure de niveaux clés avec confirmation volume.

Signal BUY : cassure au-dessus de résistance + volume > moyenne × 1.5
Signal SELL : cassure sous support + volume élevé
Timeframe  : 1h (configurable)
"""

import math

import pandas as pd
from loguru import logger

from indicators.volatility import add_atr, get_current_atr
from indicators.volume import add_volume_indicators, get_volume_ratio
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal

MIN_CANDLES = 30


class BreakoutStrategy(BaseStrategy):
    """
    Stratégie de cassure de niveaux de support/résistance.

    Identifie les cassures de niveaux clés avec confirmation du volume
    pour filtrer les faux signaux.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialise la stratégie Breakout.

        Args:
            config: Configuration (lookback_periods, volume_multiplier, atr_*).
        """
        timeframe = config.get("timeframe", "1h")
        super().__init__("breakout", config, timeframe)

        self.lookback = config.get("lookback_periods", 20)
        self.volume_multiplier = config.get("volume_multiplier", 1.5)
        self.atr_period = config.get("atr_period", 14)

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute ATR et indicateurs de volume au DataFrame."""
        df = add_atr(df, self.atr_period)
        df = add_volume_indicators(df, period=20)
        return df

    def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        current_price: float,
    ) -> TradeSignal:
        """
        Génère un signal basé sur la cassure de niveaux.

        Args:
            df: DataFrame OHLCV préparé.
            symbol: Symbole de l'actif.
            current_price: Prix courant.

        Returns:
            TradeSignal avec BUY, SELL ou HOLD.
        """
        if len(df) < MIN_CANDLES + self.lookback:
            return self._hold_signal(symbol, current_price, "Données insuffisantes")

        resistance, support = self._find_levels(df)
        volume_ratio = get_volume_ratio(df, period=20)
        atr_value = get_current_atr(df, self.atr_period)
        high_volume = volume_ratio >= self.volume_multiplier

        if atr_value <= 0 or resistance is None or support is None:
            return self._hold_signal(symbol, current_price, "Niveaux ou ATR invalides")

        # Signal BUY : cassure au-dessus de la résistance + volume élevé
        if current_price > resistance and high_volume:
            sl = resistance - (atr_value * self.config.get("atr_multiplier_sl", 1.5))
            tp = current_price + (atr_value * self.config.get("atr_multiplier_tp", 3.0))

            signal = TradeSignal(
                signal=Signal.BUY,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=min(0.9, 0.6 + (volume_ratio - self.volume_multiplier) * 0.1),
                timeframe=self.timeframe,
                reason=(
                    f"Cassure résistance {resistance:.4f} | "
                    f"Volume: {volume_ratio:.2f}x"
                ),
            )
            self.record_signal(signal)
            logger.info(
                f"[{self.name}] BUY {symbol} @ {current_price:.4f} | "
                f"Résistance: {resistance:.4f} | Vol ratio: {volume_ratio:.2f}x"
            )
            return signal

        # Signal SELL : cassure sous le support + volume élevé
        if current_price < support and high_volume:
            sl = support + (atr_value * self.config.get("atr_multiplier_sl", 1.5))
            tp = current_price - (atr_value * self.config.get("atr_multiplier_tp", 3.0))

            signal = TradeSignal(
                signal=Signal.SELL,
                symbol=symbol,
                strategy_name=self.name,
                entry_price=current_price,
                stop_loss=round(sl, 6),
                take_profit=round(tp, 6),
                confidence=min(0.9, 0.6 + (volume_ratio - self.volume_multiplier) * 0.1),
                timeframe=self.timeframe,
                reason=(
                    f"Cassure support {support:.4f} | "
                    f"Volume: {volume_ratio:.2f}x"
                ),
            )
            self.record_signal(signal)
            logger.info(
                f"[{self.name}] SELL {symbol} @ {current_price:.4f} | "
                f"Support: {support:.4f} | Vol ratio: {volume_ratio:.2f}x"
            )
            return signal

        return self._hold_signal(
            symbol, current_price,
            f"Pas de cassure | Résistance: {resistance:.4f} | Support: {support:.4f} | "
            f"Volume: {volume_ratio:.2f}x (min: {self.volume_multiplier}x)"
        )

    def _find_levels(
        self, df: pd.DataFrame
    ) -> tuple[float | None, float | None]:
        """
        Identifie les niveaux de résistance et de support.

        Utilise les hauts/bas récents sur la période de lookback.

        Args:
            df: DataFrame OHLCV.

        Returns:
            Tuple (resistance, support) ou (None, None) si insuffisant.
        """
        if len(df) < self.lookback + 2:
            return None, None

        # Exclure la dernière bougie (courante) du calcul des niveaux
        history = df.iloc[-(self.lookback + 1):-1]

        resistance = float(history["high"].max())
        support = float(history["low"].min())

        return resistance, support
