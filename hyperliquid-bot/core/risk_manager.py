"""
Gestionnaire de risque — contrôle du risque global et par trade.

Valide chaque signal de trading contre les règles de risque configurées
et calcule les tailles de position ajustées à la volatilité.
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class RiskConfig:
    """Configuration des paramètres de risque."""
    max_risk_per_trade_pct: float = 1.0       # % du capital risqué par trade
    max_drawdown_pct: float = 10.0            # drawdown max avant arrêt
    max_open_positions: int = 5               # positions simultanées max
    min_risk_reward_ratio: float = 2.0        # ratio R/R minimum
    default_leverage: int = 1                 # levier par défaut


@dataclass
class RiskCheckResult:
    """Résultat d'une vérification de risque."""
    approved: bool
    reason: str
    position_size: float = 0.0
    adjusted_sl: Optional[float] = None
    adjusted_tp: Optional[float] = None


class RiskManager:
    """
    Contrôleur de risque multi-niveaux.

    Vérifie chaque signal avant exécution et maintient les métriques
    de risque globales du portefeuille.
    """

    def __init__(self, config: RiskConfig) -> None:
        """
        Initialise le gestionnaire de risque.

        Args:
            config: Configuration des paramètres de risque.
        """
        self.config = config
        self._peak_capital: float = 0.0
        self._current_capital: float = 0.0
        self._bot_stopped: bool = False
        self._total_trades: int = 0
        self._winning_trades: int = 0
        logger.info(
            f"RiskManager initialisé — "
            f"risk/trade: {config.max_risk_per_trade_pct}% | "
            f"max drawdown: {config.max_drawdown_pct}%"
        )

    def initialize_capital(self, capital: float) -> None:
        """
        Initialise le capital de référence.

        Args:
            capital: Capital initial en USD.
        """
        self._current_capital = capital
        self._peak_capital = capital
        logger.info(f"Capital initialisé: ${capital:.2f}")

    def update_capital(self, new_capital: float) -> None:
        """
        Met à jour le capital courant et vérifie le drawdown.

        Args:
            new_capital: Nouveau capital en USD.
        """
        self._current_capital = new_capital
        if new_capital > self._peak_capital:
            self._peak_capital = new_capital

        drawdown = self.current_drawdown_pct
        if drawdown >= self.config.max_drawdown_pct and not self._bot_stopped:
            self._bot_stopped = True
            logger.critical(
                f"DRAWDOWN MAXIMUM ATTEINT ({drawdown:.2f}% >= {self.config.max_drawdown_pct}%). "
                f"Bot arrêté pour protection du capital."
            )

    def record_trade_result(self, pnl: float) -> None:
        """
        Enregistre le résultat d'un trade pour les statistiques.

        Args:
            pnl: PnL réalisé du trade en USD.
        """
        self._total_trades += 1
        if pnl > 0:
            self._winning_trades += 1

    def check_new_trade(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        current_positions_count: int,
        atr: Optional[float] = None,
    ) -> RiskCheckResult:
        """
        Vérifie si un nouveau trade peut être ouvert.

        Args:
            symbol: Symbole à trader.
            entry_price: Prix d'entrée prévu.
            stop_loss: Prix du stop-loss.
            take_profit: Prix du take-profit.
            current_positions_count: Nombre de positions déjà ouvertes.
            atr: Average True Range (pour ajustement de taille).

        Returns:
            RiskCheckResult avec approbation et taille de position calculée.
        """
        if self._bot_stopped:
            return RiskCheckResult(
                approved=False,
                reason=f"Bot arrêté — drawdown max atteint ({self.current_drawdown_pct:.2f}%)",
            )

        if current_positions_count >= self.config.max_open_positions:
            return RiskCheckResult(
                approved=False,
                reason=f"Nombre max de positions atteint ({self.config.max_open_positions})",
            )

        if self._current_capital <= 0:
            return RiskCheckResult(
                approved=False,
                reason="Capital insuffisant.",
            )

        risk_in_price = abs(entry_price - stop_loss)
        if risk_in_price <= 0:
            return RiskCheckResult(
                approved=False,
                reason="Stop-loss invalide (risque nul ou négatif).",
            )

        reward_in_price = abs(take_profit - entry_price)
        risk_reward_ratio = reward_in_price / risk_in_price if risk_in_price > 0 else 0

        if risk_reward_ratio < self.config.min_risk_reward_ratio:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Ratio R/R insuffisant: {risk_reward_ratio:.2f} "
                    f"(minimum: {self.config.min_risk_reward_ratio})"
                ),
            )

        position_size = self.calculate_position_size(entry_price, stop_loss)

        logger.debug(
            f"Vérification risque OK — {symbol}: "
            f"size={position_size:.6f} | R/R={risk_reward_ratio:.2f} | "
            f"risk=${self._current_capital * self.config.max_risk_per_trade_pct / 100:.2f}"
        )

        return RiskCheckResult(
            approved=True,
            reason="OK",
            position_size=position_size,
        )

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        risk_pct: Optional[float] = None,
    ) -> float:
        """
        Calcule la taille de position basée sur le risque et le stop-loss.

        Position size = (Capital × Risk%) / (Entry - StopLoss)

        Args:
            entry_price: Prix d'entrée.
            stop_loss: Prix du stop-loss.
            risk_pct: Pourcentage du capital à risquer (défaut: config).

        Returns:
            Taille de la position en unités de l'actif.
        """
        if self._current_capital <= 0 or entry_price <= 0:
            return 0.0

        pct = risk_pct if risk_pct is not None else self.config.max_risk_per_trade_pct
        risk_amount = self._current_capital * (pct / 100)
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit <= 0:
            return 0.0

        size = risk_amount / risk_per_unit
        return round(size, 6)

    def calculate_atr_stop_loss(
        self,
        entry_price: float,
        atr: float,
        is_long: bool,
        multiplier: float = 2.0,
    ) -> float:
        """
        Calcule le stop-loss basé sur l'ATR.

        Args:
            entry_price: Prix d'entrée.
            atr: Average True Range.
            is_long: True pour position longue, False pour courte.
            multiplier: Multiplicateur ATR pour le SL.

        Returns:
            Prix du stop-loss.
        """
        if is_long:
            return entry_price - (atr * multiplier)
        return entry_price + (atr * multiplier)

    def calculate_atr_take_profit(
        self,
        entry_price: float,
        atr: float,
        is_long: bool,
        multiplier: float = 4.0,
    ) -> float:
        """
        Calcule le take-profit basé sur l'ATR.

        Args:
            entry_price: Prix d'entrée.
            atr: Average True Range.
            is_long: True pour position longue, False pour courte.
            multiplier: Multiplicateur ATR pour le TP.

        Returns:
            Prix du take-profit.
        """
        if is_long:
            return entry_price + (atr * multiplier)
        return entry_price - (atr * multiplier)

    @property
    def current_drawdown_pct(self) -> float:
        """Calcule le drawdown actuel en pourcentage depuis le pic."""
        if self._peak_capital <= 0:
            return 0.0
        return ((self._peak_capital - self._current_capital) / self._peak_capital) * 100

    @property
    def win_rate(self) -> float:
        """Calcule le taux de victoire en pourcentage."""
        if self._total_trades == 0:
            return 0.0
        return (self._winning_trades / self._total_trades) * 100

    @property
    def is_bot_stopped(self) -> bool:
        """Indique si le bot a été arrêté pour protection du capital."""
        return self._bot_stopped

    def reset_stop(self) -> None:
        """Réactive le bot après intervention manuelle (si drawdown récupéré)."""
        if self.current_drawdown_pct < self.config.max_drawdown_pct:
            self._bot_stopped = False
            logger.warning("Bot réactivé manuellement après arrêt drawdown.")

    def get_stats(self) -> dict:
        """Retourne les statistiques de risque pour le dashboard."""
        return {
            "current_capital": self._current_capital,
            "peak_capital": self._peak_capital,
            "drawdown_pct": round(self.current_drawdown_pct, 2),
            "max_drawdown_pct": self.config.max_drawdown_pct,
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(self.win_rate, 1),
            "bot_stopped": self._bot_stopped,
            "max_risk_per_trade_pct": self.config.max_risk_per_trade_pct,
            "max_open_positions": self.config.max_open_positions,
        }
