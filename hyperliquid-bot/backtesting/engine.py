"""
Moteur de backtesting — simulation de stratégies sur données historiques.

Rejoue une stratégie sur des données OHLCV historiques en simulant
les ordres, frais et gestion du risque pour évaluer les performances.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from core.risk_manager import RiskConfig, RiskManager
from strategies.base_strategy import BaseStrategy, Signal


@dataclass
class BacktestTrade:
    """Trade enregistré pendant le backtesting."""
    entry_index: int
    entry_price: float
    entry_time: datetime
    side: str
    size: float
    stop_loss: float
    take_profit: float
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    duration_bars: int = 0


@dataclass
class BacktestResult:
    """Résultat complet d'un backtesting."""
    strategy_name: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        """Rendement total en %."""
        if self.initial_capital <= 0:
            return 0.0
        return ((self.final_capital - self.initial_capital) / self.initial_capital) * 100

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losing_trades(self) -> list[BacktestTrade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (len(self.winning_trades) / self.total_trades) * 100

    @property
    def avg_win(self) -> float:
        wins = self.winning_trades
        if not wins:
            return 0.0
        return sum(t.pnl for t in wins) / len(wins)

    @property
    def avg_loss(self) -> float:
        losses = self.losing_trades
        if not losses:
            return 0.0
        return sum(t.pnl for t in losses) / len(losses)

    @property
    def profit_factor(self) -> float:
        total_wins = sum(t.pnl for t in self.winning_trades)
        total_losses = abs(sum(t.pnl for t in self.losing_trades))
        if total_losses == 0:
            return float("inf") if total_wins > 0 else 0.0
        return total_wins / total_losses

    @property
    def max_drawdown_pct(self) -> float:
        """Calcule le drawdown maximum sur la courbe d'équity."""
        if len(self.equity_curve) < 2:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            dd = ((peak - equity) / peak) * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def sharpe_ratio(self) -> float:
        """Calcule le ratio de Sharpe annualisé (approximatif)."""
        if len(self.trades) < 2:
            return 0.0
        returns = [t.pnl_pct for t in self.trades]
        import statistics
        avg_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0
        if std_return == 0:
            return 0.0
        return (avg_return / std_return) * (252 ** 0.5)


class BacktestEngine:
    """
    Moteur de backtesting pour les stratégies HyperBot.

    Simule l'exécution d'une stratégie sur des données historiques
    en respectant les règles de risque et les frais de trading.
    """

    DEFAULT_FEE_PCT = 0.04       # 0.04% frais taker
    DEFAULT_SLIPPAGE_PCT = 0.05  # 0.05% slippage

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 10_000.0,
        risk_pct: float = 1.0,
        fee_pct: float = DEFAULT_FEE_PCT,
        slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
        max_open_positions: int = 1,
    ) -> None:
        """
        Initialise le moteur de backtesting.

        Args:
            strategy: Stratégie à tester.
            initial_capital: Capital initial en USD.
            risk_pct: % du capital risqué par trade.
            fee_pct: Frais de transaction en %.
            slippage_pct: Slippage simulé en %.
            max_open_positions: Nombre max de positions simultanées.
        """
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk_pct = risk_pct
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.max_open_positions = max_open_positions

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        warmup_bars: int = 220,
    ) -> BacktestResult:
        """
        Exécute le backtesting sur un DataFrame OHLCV.

        Args:
            df: DataFrame OHLCV complet.
            symbol: Symbole testé.
            warmup_bars: Bougies initiales ignorées (pour les indicateurs).

        Returns:
            BacktestResult avec toutes les métriques.
        """
        if len(df) < warmup_bars + 10:
            logger.error(f"Données insuffisantes pour backtesting: {len(df)} bougies")
            return self._empty_result(symbol, df)

        df = self.strategy.prepare_dataframe(df.copy())

        capital = float(self.initial_capital)
        open_trades: list[BacktestTrade] = []
        closed_trades: list[BacktestTrade] = []
        equity_curve = [capital]

        start_time = df.iloc[warmup_bars]["timestamp"] if "timestamp" in df.columns else datetime.utcnow()
        end_time = df.iloc[-1]["timestamp"] if "timestamp" in df.columns else datetime.utcnow()

        for i in range(warmup_bars, len(df)):
            current_bar = df.iloc[i]
            current_price = float(current_bar["close"])
            current_high = float(current_bar["high"])
            current_low = float(current_bar["low"])

            # Vérifier SL/TP des positions ouvertes
            still_open = []
            for trade in open_trades:
                closed, exit_price, reason = self._check_exit(
                    trade, current_high, current_low, current_price
                )
                if closed:
                    self._close_trade(trade, exit_price, reason, i, capital)
                    capital += trade.pnl
                    closed_trades.append(trade)
                else:
                    still_open.append(trade)
            open_trades = still_open

            # Générer signal si pas au max de positions
            if len(open_trades) < self.max_open_positions:
                df_slice = df.iloc[:i + 1]
                signal = self.strategy.generate_signal(df_slice, symbol, current_price)

                if signal.signal != Signal.HOLD:
                    entry_price = self._apply_slippage(
                        current_price,
                        signal.signal == Signal.BUY
                    )
                    size = self.strategy.calculate_position_size(
                        capital, self.risk_pct, entry_price, signal.stop_loss
                    )

                    if size > 0:
                        fee = entry_price * size * (self.fee_pct / 100)
                        capital -= fee

                        trade = BacktestTrade(
                            entry_index=i,
                            entry_price=entry_price,
                            entry_time=current_bar.get("timestamp", datetime.utcnow()),
                            side="long" if signal.signal == Signal.BUY else "short",
                            size=size,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                        )
                        open_trades.append(trade)

            # Snapshot d'équity
            unrealized = sum(
                (current_price - t.entry_price) * t.size
                if t.side == "long"
                else (t.entry_price - current_price) * t.size
                for t in open_trades
            )
            equity_curve.append(capital + unrealized)

        # Forcer la fermeture des positions restantes
        last_price = float(df.iloc[-1]["close"])
        for trade in open_trades:
            self._close_trade(trade, last_price, "end_of_data", len(df) - 1, capital)
            capital += trade.pnl
            closed_trades.append(trade)

        start = start_time if isinstance(start_time, datetime) else datetime.utcnow()
        end = end_time if isinstance(end_time, datetime) else datetime.utcnow()

        result = BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            timeframe=self.strategy.timeframe,
            start_date=start,
            end_date=end,
            initial_capital=self.initial_capital,
            final_capital=capital,
            trades=closed_trades,
            equity_curve=equity_curve,
        )

        logger.info(
            f"Backtest terminé — {self.strategy.name} {symbol}: "
            f"{len(closed_trades)} trades | "
            f"Rendement: {result.total_return_pct:+.2f}% | "
            f"Win rate: {result.win_rate:.1f}%"
        )
        return result

    def _check_exit(
        self,
        trade: BacktestTrade,
        high: float,
        low: float,
        close: float,
    ) -> tuple[bool, float, str]:
        """Vérifie si une position doit être fermée (SL/TP)."""
        if trade.side == "long":
            if low <= trade.stop_loss:
                return True, trade.stop_loss, "sl"
            if high >= trade.take_profit:
                return True, trade.take_profit, "tp"
        else:  # short
            if high >= trade.stop_loss:
                return True, trade.stop_loss, "sl"
            if low <= trade.take_profit:
                return True, trade.take_profit, "tp"
        return False, close, ""

    def _close_trade(
        self,
        trade: BacktestTrade,
        exit_price: float,
        reason: str,
        exit_bar: int,
        current_capital: float,
    ) -> None:
        """Calcule le PnL et ferme un trade."""
        exit_price = self._apply_slippage(exit_price, trade.side == "short")
        fee = exit_price * trade.size * (self.fee_pct / 100)

        if trade.side == "long":
            gross_pnl = (exit_price - trade.entry_price) * trade.size
        else:
            gross_pnl = (trade.entry_price - exit_price) * trade.size

        trade.pnl = gross_pnl - fee
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.duration_bars = exit_bar - trade.entry_index
        notional = trade.entry_price * trade.size
        trade.pnl_pct = (trade.pnl / notional * 100) if notional > 0 else 0

    def _apply_slippage(self, price: float, adverse: bool) -> float:
        """Applique le slippage dans le sens défavorable."""
        slippage = price * (self.slippage_pct / 100)
        return price + slippage if adverse else price - slippage

    def _empty_result(self, symbol: str, df: pd.DataFrame) -> BacktestResult:
        """Retourne un résultat vide en cas d'erreur."""
        return BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            timeframe=self.strategy.timeframe,
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow(),
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
        )
