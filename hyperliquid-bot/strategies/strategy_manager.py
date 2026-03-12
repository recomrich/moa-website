"""
Orchestrateur des stratégies — charge et exécute les stratégies actives.

Coordonne l'exécution des stratégies sur les paires configurées,
applique les filtres de risque et transmet les signaux au bot principal.
"""

from typing import Callable, Optional

import pandas as pd
from loguru import logger

from data.feed import DataFeed
from strategies.base_strategy import BaseStrategy, Signal, TradeSignal
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.scalping import ScalpingStrategy
from strategies.trend_following import TrendFollowingStrategy

# Registre des classes de stratégies disponibles
STRATEGY_REGISTRY: dict[str, type] = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
    "scalping": ScalpingStrategy,
}


class StrategyManager:
    """
    Gestionnaire et orchestrateur des stratégies de trading.

    Charge les stratégies depuis la configuration, récupère les données
    nécessaires et génère les signaux pour chaque paire active.
    """

    def __init__(
        self,
        config: dict,
        data_feed: DataFeed,
        signal_callback: Optional[Callable[[TradeSignal, str], None]] = None,
    ) -> None:
        """
        Initialise le gestionnaire de stratégies.

        Args:
            config: Configuration complète (depuis config.yaml).
            data_feed: Flux de données de marché.
            signal_callback: Callback appelé pour chaque signal actionnable.
        """
        self.config = config
        self.data_feed = data_feed
        self.signal_callback = signal_callback

        self._strategies: dict[str, BaseStrategy] = {}
        self._pair_strategies: list[dict] = []

        self._load_strategies()
        self._load_pairs()
        logger.info(
            f"StrategyManager initialisé — "
            f"{len(self._strategies)} stratégies | "
            f"{len(self._pair_strategies)} paires actives"
        )

    def _load_strategies(self) -> None:
        """Charge et instancie les stratégies depuis la configuration."""
        strategies_config = self.config.get("strategies", {})

        for name, cls in STRATEGY_REGISTRY.items():
            strat_config = strategies_config.get(name, {})
            if not strat_config.get("enabled", False):
                logger.debug(f"Stratégie {name} désactivée.")
                continue

            try:
                strategy = cls(strat_config)
                self._strategies[name] = strategy
                logger.info(f"Stratégie chargée: {name} ({strategy.timeframe})")
            except Exception as exc:
                logger.error(f"Erreur chargement stratégie {name}: {exc}")

    def _load_pairs(self) -> None:
        """Charge les paires de trading et leurs stratégies associées."""
        trading_pairs = self.config.get("trading_pairs", {})

        for market_type in ["spot", "perps"]:
            pairs = trading_pairs.get(market_type, [])
            for pair_config in pairs:
                symbol = pair_config.get("symbol")
                pair_strategies = pair_config.get("strategies", [])
                leverage = pair_config.get("leverage", 1)

                if not symbol:
                    continue

                active_strategies = [
                    s for s in pair_strategies
                    if s in self._strategies
                ]

                if active_strategies:
                    self._pair_strategies.append({
                        "symbol": symbol,
                        "market_type": market_type,
                        "leverage": leverage,
                        "strategies": active_strategies,
                    })
                    logger.debug(
                        f"Paire ajoutée: {symbol} ({market_type}) — "
                        f"stratégies: {active_strategies}"
                    )

    async def run_cycle(self) -> list[TradeSignal]:
        """
        Exécute un cycle complet d'analyse pour toutes les paires.

        Récupère les données OHLCV, applique les indicateurs et génère
        les signaux pour chaque paire × stratégie.

        Returns:
            Liste des TradeSignals actionnables (BUY ou SELL).
        """
        actionable_signals = []

        for pair_info in self._pair_strategies:
            symbol = pair_info["symbol"]
            market_type = pair_info["market_type"]
            leverage = pair_info["leverage"]

            current_price = self.data_feed.get_current_price(symbol)
            if current_price is None:
                logger.warning(f"Prix indisponible pour {symbol}, skip.")
                continue

            for strategy_name in pair_info["strategies"]:
                strategy = self._strategies.get(strategy_name)
                if strategy is None or not strategy.enabled:
                    continue

                signal = self._run_strategy(strategy, symbol, current_price)

                if signal and signal.signal != Signal.HOLD:
                    signal_with_meta = self._enrich_signal(signal, market_type, leverage)
                    actionable_signals.append(signal_with_meta)

                    if self.signal_callback:
                        try:
                            self.signal_callback(signal_with_meta, market_type)
                        except Exception as exc:
                            logger.error(f"Erreur signal_callback: {exc}")

        return actionable_signals

    def _run_strategy(
        self,
        strategy: BaseStrategy,
        symbol: str,
        current_price: float,
    ) -> Optional[TradeSignal]:
        """
        Exécute une stratégie sur un symbole.

        Args:
            strategy: Instance de stratégie.
            symbol: Symbole de l'actif.
            current_price: Prix courant.

        Returns:
            TradeSignal généré ou None si erreur.
        """
        try:
            df = self.data_feed.get_ohlcv(symbol, strategy.timeframe, limit=500)
            if df is None or df.empty:
                logger.warning(f"Données vides pour {symbol} {strategy.timeframe}")
                return None

            df = strategy.prepare_dataframe(df)
            signal = strategy.generate_signal(df, symbol, current_price)
            return signal

        except Exception as exc:
            logger.error(
                f"Erreur stratégie {strategy.name} sur {symbol}: {exc}",
                exc_info=True,
            )
            return None

    def _enrich_signal(
        self, signal: TradeSignal, market_type: str, leverage: int
    ) -> TradeSignal:
        """Ajoute les métadonnées de marché au signal."""
        signal.reason = f"[{market_type.upper()}|{leverage}x] " + signal.reason
        return signal

    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """Retourne une stratégie par son nom."""
        return self._strategies.get(name)

    def get_all_stats(self) -> list[dict]:
        """Retourne les statistiques de toutes les stratégies."""
        return [s.get_stats_dict() for s in self._strategies.values()]

    def record_trade_result(self, strategy_name: str, pnl: float) -> None:
        """
        Enregistre le résultat d'un trade pour une stratégie.

        Args:
            strategy_name: Nom de la stratégie.
            pnl: PnL réalisé en USD.
        """
        strategy = self._strategies.get(strategy_name)
        if strategy:
            strategy.record_trade_result(pnl)
