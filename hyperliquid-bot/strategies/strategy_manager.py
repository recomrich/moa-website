"""Strategy manager - loads, orchestrates, and executes active strategies."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from loguru import logger

from strategies.base_strategy import BaseStrategy, Signal
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.scalping import ScalpingStrategy
from strategies.trend_following import TrendFollowingStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
    "scalping": ScalpingStrategy,
}


class StrategyManager:
    """Loads, manages, and executes trading strategies."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._strategies: dict[str, BaseStrategy] = {}
        self._load_strategies()

    def _load_strategies(self) -> None:
        """Load strategies from configuration."""
        strategies_config = self._config.get("strategies", {})

        for name, params in strategies_config.items():
            if not params.get("enabled", False):
                logger.info(f"Strategy '{name}' is disabled, skipping")
                continue

            strategy_class = STRATEGY_REGISTRY.get(name)
            if strategy_class is None:
                logger.warning(f"Unknown strategy: {name}")
                continue

            strategy = strategy_class(params)
            self._strategies[name] = strategy
            logger.info(
                f"Loaded strategy: {name} "
                f"(timeframe={strategy.timeframe})"
            )

    def run_strategy(
        self, strategy_name: str, df: pd.DataFrame
    ) -> Optional[Signal]:
        """Run a specific strategy against market data."""
        strategy = self._strategies.get(strategy_name)
        if strategy is None or not strategy.enabled:
            return None

        try:
            signal = strategy.generate_signal(df)
            return signal
        except Exception as e:
            logger.error(f"Strategy '{strategy_name}' error: {e}")
            return None

    def run_all(
        self, data_by_timeframe: dict[str, pd.DataFrame]
    ) -> dict[str, Signal]:
        """Run all active strategies and return signals.

        Args:
            data_by_timeframe: Dict mapping timeframe -> DataFrame.

        Returns:
            Dict mapping strategy_name -> Signal.
        """
        signals: dict[str, Signal] = {}

        for name, strategy in self._strategies.items():
            if not strategy.enabled:
                continue

            df = data_by_timeframe.get(strategy.timeframe)
            if df is None or df.empty:
                logger.debug(
                    f"No data for timeframe {strategy.timeframe} "
                    f"(strategy: {name})"
                )
                continue

            signal = self.run_strategy(name, df)
            if signal is not None:
                signals[name] = signal

        return signals

    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        return self._strategies.get(name)

    def get_all_strategies(self) -> dict[str, BaseStrategy]:
        return self._strategies.copy()

    def get_all_statuses(self) -> list[dict]:
        """Get status of all strategies for dashboard."""
        return [s.get_status() for s in self._strategies.values()]

    def enable_strategy(self, name: str) -> bool:
        """Enable a strategy at runtime."""
        strategy = self._strategies.get(name)
        if strategy:
            strategy.enabled = True
            logger.info(f"Strategy enabled: {name}")
            return True
        return False

    def disable_strategy(self, name: str) -> bool:
        """Disable a strategy at runtime."""
        strategy = self._strategies.get(name)
        if strategy:
            strategy.enabled = False
            logger.info(f"Strategy disabled: {name}")
            return True
        return False

    def get_required_timeframes(self) -> set[str]:
        """Get all unique timeframes needed by active strategies."""
        return {
            s.timeframe for s in self._strategies.values() if s.enabled
        }

    def get_strategies_for_symbol(
        self, symbol: str, trading_pairs_config: list[dict]
    ) -> list[str]:
        """Get strategy names configured for a specific symbol."""
        for pair in trading_pairs_config:
            if pair.get("symbol") == symbol:
                return pair.get("strategies", [])
        return []
