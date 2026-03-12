"""
Classe abstraite de base pour toutes les stratégies de trading.

Définit l'interface commune que toutes les stratégies doivent implémenter,
avec les méthodes de génération de signal et de calcul de position.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


class Signal(Enum):
    """Signal de trading généré par une stratégie."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """Signal complet avec tous les paramètres d'ordre."""
    signal: Signal
    symbol: str
    strategy_name: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float = 0.0
    confidence: float = 1.0      # Score de confiance 0-1
    timeframe: str = "1h"
    reason: str = ""
    generated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def risk_reward_ratio(self) -> float:
        """Calcule le ratio risk/reward du signal."""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        if risk == 0:
            return 0.0
        return reward / risk


@dataclass
class StrategyStats:
    """Statistiques de performance d'une stratégie."""
    name: str
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        """Taux de victoire en pourcentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def avg_pnl(self) -> float:
        """PnL moyen par trade."""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades


class BaseStrategy(ABC):
    """
    Classe abstraite dont héritent toutes les stratégies.

    Fournit l'interface commune et les utilitaires partagés.
    Chaque stratégie doit implémenter generate_signal() au minimum.
    """

    def __init__(self, name: str, config: dict, timeframe: str) -> None:
        """
        Initialise la stratégie.

        Args:
            name: Nom unique de la stratégie.
            config: Configuration spécifique (depuis config.yaml).
            timeframe: Intervalle de temps de la stratégie.
        """
        self.name = name
        self.config = config
        self.timeframe = timeframe
        self.enabled: bool = config.get("enabled", True)
        self.stats = StrategyStats(name=name)
        self._last_signal: Optional[TradeSignal] = None

    @abstractmethod
    def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        current_price: float,
    ) -> TradeSignal:
        """
        Génère un signal de trading basé sur les données OHLCV.

        Args:
            df: DataFrame OHLCV avec les indicateurs calculés.
            symbol: Symbole de l'actif.
            current_price: Prix courant de l'actif.

        Returns:
            TradeSignal avec le signal et les paramètres d'ordre.
        """
        ...

    @abstractmethod
    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ajoute les indicateurs spécifiques à la stratégie sur le DataFrame.

        Args:
            df: DataFrame OHLCV brut.

        Returns:
            DataFrame avec indicateurs ajoutés.
        """
        ...

    def calculate_position_size(
        self,
        capital: float,
        risk_pct: float,
        entry_price: float,
        stop_loss: float,
    ) -> float:
        """
        Calcule la taille de position basée sur le risque.

        Position size = (Capital × Risk%) / |Entry - StopLoss|

        Args:
            capital: Capital disponible en USD.
            risk_pct: Pourcentage du capital à risquer.
            entry_price: Prix d'entrée.
            stop_loss: Prix du stop-loss.

        Returns:
            Taille de la position en unités de l'actif.
        """
        if capital <= 0 or entry_price <= 0:
            return 0.0

        risk_amount = capital * (risk_pct / 100)
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit <= 0:
            return 0.0

        return round(risk_amount / risk_per_unit, 6)

    def get_stop_loss(
        self,
        entry_price: float,
        atr: float,
        is_long: bool,
        multiplier: Optional[float] = None,
    ) -> float:
        """
        Calcule le stop-loss basé sur l'ATR.

        Args:
            entry_price: Prix d'entrée.
            atr: Average True Range.
            is_long: True pour position longue.
            multiplier: Multiplicateur ATR (défaut: depuis config).

        Returns:
            Prix du stop-loss.
        """
        mult = multiplier or self.config.get("atr_multiplier_sl", 2.0)
        if is_long:
            return entry_price - (atr * mult)
        return entry_price + (atr * mult)

    def get_take_profit(
        self,
        entry_price: float,
        atr: float,
        is_long: bool,
        multiplier: Optional[float] = None,
    ) -> float:
        """
        Calcule le take-profit basé sur l'ATR.

        Args:
            entry_price: Prix d'entrée.
            atr: Average True Range.
            is_long: True pour position longue.
            multiplier: Multiplicateur ATR (défaut: depuis config).

        Returns:
            Prix du take-profit.
        """
        mult = multiplier or self.config.get("atr_multiplier_tp", 4.0)
        if is_long:
            return entry_price + (atr * mult)
        return entry_price - (atr * mult)

    def record_signal(self, signal: TradeSignal) -> None:
        """Enregistre un signal pour les statistiques."""
        self.stats.total_signals += 1
        if signal.signal == Signal.BUY:
            self.stats.buy_signals += 1
        elif signal.signal == Signal.SELL:
            self.stats.sell_signals += 1
        self._last_signal = signal

    def record_trade_result(self, pnl: float) -> None:
        """Enregistre le résultat d'un trade pour les statistiques."""
        self.stats.total_trades += 1
        self.stats.total_pnl += pnl
        if pnl > 0:
            self.stats.winning_trades += 1
        else:
            self.stats.losing_trades += 1

    def get_stats_dict(self) -> dict:
        """Retourne les statistiques sérialisées pour le dashboard."""
        return {
            "name": self.stats.name,
            "enabled": self.enabled,
            "timeframe": self.timeframe,
            "total_signals": self.stats.total_signals,
            "buy_signals": self.stats.buy_signals,
            "sell_signals": self.stats.sell_signals,
            "total_trades": self.stats.total_trades,
            "win_rate": round(self.stats.win_rate, 1),
            "total_pnl": round(self.stats.total_pnl, 2),
            "avg_pnl": round(self.stats.avg_pnl, 4),
            "last_signal": self._last_signal.signal.value if self._last_signal else None,
        }

    def _hold_signal(self, symbol: str, current_price: float, reason: str = "") -> TradeSignal:
        """Crée un signal HOLD (pas d'action)."""
        return TradeSignal(
            signal=Signal.HOLD,
            symbol=symbol,
            strategy_name=self.name,
            entry_price=current_price,
            stop_loss=current_price * 0.95,
            take_profit=current_price * 1.05,
            reason=reason,
        )
