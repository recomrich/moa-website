"""Strategy manager - loads, orchestrates, and executes active strategies."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from loguru import logger

from strategies.base_strategy import BaseStrategy, Signal
from strategies.breakout import BreakoutStrategy
from strategies.grid_trading import GridTradingStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.scalping import ScalpingStrategy
from strategies.trend_following import TrendFollowingStrategy
from strategies.regime_detector import RegimeDetector, MarketRegime

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
    "scalping": ScalpingStrategy,
    "grid_trading": GridTradingStrategy,
}

# Higher timeframe for confirmation
CONFIRMATION_TIMEFRAMES: dict[str, str] = {
    "5m": "1h",
    "15m": "1h",
    "1h": "4h",
    "4h": "1d",
}


class StrategyManager:
    """Loads, manages, and executes trading strategies."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._strategies: dict[str, BaseStrategy] = {}
        self._regime_detector = RegimeDetector()
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

    def run_with_confirmation(
        self,
        strategy_name: str,
        df: pd.DataFrame,
        higher_tf_df: Optional[pd.DataFrame] = None,
        symbol: str = "",
    ) -> Optional[Signal]:
        """Run strategy with multi-timeframe confirmation and regime check.

        Signal is only valid if:
        1. The strategy generates BUY or SELL
        2. The higher timeframe trend agrees (if data available)
        3. The market regime is suitable for this strategy
        """
        signal = self.run_strategy(strategy_name, df)
        if signal is None or signal == Signal.HOLD:
            return signal

        # Regime check: is this strategy suitable for current conditions?
        if symbol and not df.empty:
            regime = self._regime_detector.detect(df, symbol)
            recommended = self._regime_detector.get_recommended_strategies(regime)
            if strategy_name not in recommended:
                logger.debug(
                    f"[{strategy_name}] Signal {signal.value} ignored - "
                    f"regime {regime.value} favors {recommended}"
                )
                return Signal.HOLD

        # Multi-timeframe confirmation
        if higher_tf_df is not None and not higher_tf_df.empty:
            from indicators.trend import ema
            from indicators.momentum import rsi as calc_rsi

            htf_ema20 = ema(higher_tf_df, 20)
            htf_ema50 = ema(higher_tf_df, 50)

            if not htf_ema20.empty and not htf_ema50.empty:
                htf_trend_up = htf_ema20.iloc[-1] > htf_ema50.iloc[-1]

                if signal == Signal.BUY and not htf_trend_up:
                    logger.info(
                        f"[{strategy_name}] BUY rejected - "
                        f"higher timeframe trend is bearish"
                    )
                    return Signal.HOLD

                if signal == Signal.SELL and htf_trend_up:
                    logger.info(
                        f"[{strategy_name}] SELL rejected - "
                        f"higher timeframe trend is bullish"
                    )
                    return Signal.HOLD

        return signal

    def get_consensus(
        self,
        signals: dict[str, Signal],
        min_agree: int = 2,
    ) -> Optional[Signal]:
        """Check if multiple strategies agree on a direction.

        Returns the consensus signal if enough strategies agree.
        """
        buy_count = sum(1 for s in signals.values() if s == Signal.BUY)
        sell_count = sum(1 for s in signals.values() if s == Signal.SELL)

        if buy_count >= min_agree:
            logger.info(
                f"[CONSENSUS] BUY confirmed by {buy_count} strategies"
            )
            return Signal.BUY

        if sell_count >= min_agree:
            logger.info(
                f"[CONSENSUS] SELL confirmed by {sell_count} strategies"
            )
            return Signal.SELL

        return None

    @property
    def regime_detector(self) -> RegimeDetector:
        return self._regime_detector

    def run_all(
        self, data_by_timeframe: dict[str, pd.DataFrame]
    ) -> dict[str, Signal]:
        """Run all active strategies and return signals."""
        signals: dict[str, Signal] = {}

        for name, strategy in self._strategies.items():
            if not strategy.enabled:
                continue

            df = data_by_timeframe.get(strategy.timeframe)
            if df is None or df.empty:
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
        strategy = self._strategies.get(name)
        if strategy:
            strategy.enabled = True
            logger.info(f"Strategy enabled: {name}")
            return True
        return False

    def disable_strategy(self, name: str) -> bool:
        strategy = self._strategies.get(name)
        if strategy:
            strategy.enabled = False
            logger.info(f"Strategy disabled: {name}")
            return True
        return False

    def get_required_timeframes(self) -> set[str]:
        """Get all unique timeframes needed (including confirmation TFs)."""
        timeframes = set()
        for s in self._strategies.values():
            if s.enabled:
                timeframes.add(s.timeframe)
                htf = CONFIRMATION_TIMEFRAMES.get(s.timeframe)
                if htf:
                    timeframes.add(htf)
        return timeframes

    def get_strategies_for_symbol(
        self, symbol: str, trading_pairs_config: list[dict]
    ) -> list[str]:
        for pair in trading_pairs_config:
            if pair.get("symbol") == symbol:
                return pair.get("strategies", [])
        return []
