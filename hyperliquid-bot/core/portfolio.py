"""
Gestionnaire de portefeuille — suivi du capital et des performances.

Maintient l'historique de la courbe d'équity, calcule les métriques
de performance et synchronise avec l'exchange en mode live.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from core.client import HyperliquidClient


@dataclass
class EquityPoint:
    """Point de la courbe d'équity."""
    timestamp: datetime
    equity: float
    unrealized_pnl: float
    realized_pnl_today: float


@dataclass
class TradeRecord:
    """Enregistrement d'un trade fermé."""
    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    duration_seconds: float
    strategy_name: Optional[str]
    close_reason: str
    closed_at: datetime = field(default_factory=datetime.utcnow)


class Portfolio:
    """
    Suivi du portefeuille et calcul des performances.

    Gère le capital (réel ou virtuel), l'historique des trades
    et les métriques de performance (Sharpe, drawdown, etc.).
    """

    MAX_EQUITY_POINTS = 1440  # 24h à 1 point/minute

    def __init__(
        self,
        client: HyperliquidClient,
        initial_capital: float,
        paper_mode: bool = True,
    ) -> None:
        """
        Initialise le portefeuille.

        Args:
            client: Client Hyperliquid.
            initial_capital: Capital de départ en USD.
            paper_mode: True pour simulation, False pour live.
        """
        self.client = client
        self.paper_mode = paper_mode

        self._initial_capital = initial_capital
        self._current_equity = initial_capital
        self._realized_pnl_today = 0.0
        self._total_realized_pnl = 0.0

        self._equity_history: list[EquityPoint] = []
        self._trade_history: list[TradeRecord] = []

        self._today_date = datetime.utcnow().date()

        logger.info(
            f"Portfolio initialisé — capital: ${initial_capital:.2f} | "
            f"mode: {'paper' if paper_mode else 'LIVE'}"
        )

    def update_equity(self, unrealized_pnl: float = 0.0) -> None:
        """
        Met à jour la valeur du portefeuille et enregistre un point d'équity.

        Args:
            unrealized_pnl: PnL non réalisé des positions ouvertes.
        """
        today = datetime.utcnow().date()
        if today != self._today_date:
            self._realized_pnl_today = 0.0
            self._today_date = today

        if not self.paper_mode:
            live_equity = self._fetch_live_equity()
            if live_equity is not None:
                self._current_equity = live_equity

        total_equity = self._current_equity + unrealized_pnl

        point = EquityPoint(
            timestamp=datetime.utcnow(),
            equity=total_equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=self._realized_pnl_today,
        )

        self._equity_history.append(point)
        if len(self._equity_history) > self.MAX_EQUITY_POINTS:
            self._equity_history.pop(0)

    def record_trade(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        pnl: float,
        strategy_name: Optional[str],
        close_reason: str,
        opened_at: datetime,
    ) -> TradeRecord:
        """
        Enregistre un trade fermé et met à jour les métriques.

        Args:
            position_id: ID de la position.
            symbol: Symbole tradé.
            side: "long" ou "short".
            entry_price: Prix d'entrée.
            exit_price: Prix de sortie.
            size: Taille de la position.
            pnl: PnL réalisé en USD.
            strategy_name: Stratégie ayant généré le trade.
            close_reason: Raison de fermeture.
            opened_at: Moment d'ouverture.

        Returns:
            TradeRecord créé.
        """
        now = datetime.utcnow()
        duration = (now - opened_at).total_seconds()
        notional = entry_price * size
        pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0

        record = TradeRecord(
            id=position_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            pnl=pnl,
            pnl_pct=round(pnl_pct, 3),
            duration_seconds=duration,
            strategy_name=strategy_name,
            close_reason=close_reason,
            closed_at=now,
        )

        self._trade_history.append(record)
        self._realized_pnl_today += pnl
        self._total_realized_pnl += pnl
        self._current_equity += pnl

        logger.info(
            f"Trade enregistré: {symbol} {side} | "
            f"PnL: ${pnl:+.2f} ({pnl_pct:+.2f}%) | "
            f"Raison: {close_reason}"
        )
        return record

    def get_equity_history(self, limit: int = 100) -> list[dict]:
        """
        Retourne l'historique d'équity sérialisé.

        Args:
            limit: Nombre maximum de points retournés.

        Returns:
            Liste de points {timestamp, equity, unrealized_pnl}.
        """
        points = self._equity_history[-limit:]
        return [
            {
                "timestamp": p.timestamp.isoformat(),
                "equity": round(p.equity, 2),
                "unrealized_pnl": round(p.unrealized_pnl, 2),
                "realized_pnl_today": round(p.realized_pnl_today, 2),
            }
            for p in points
        ]

    def get_trade_history(self, limit: int = 50) -> list[dict]:
        """
        Retourne l'historique des trades sérialisé.

        Args:
            limit: Nombre maximum de trades retournés.

        Returns:
            Liste de trades.
        """
        trades = self._trade_history[-limit:]
        return [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size": t.size,
                "pnl": round(t.pnl, 4),
                "pnl_pct": t.pnl_pct,
                "strategy": t.strategy_name,
                "close_reason": t.close_reason,
                "duration_min": round(t.duration_seconds / 60, 1),
                "closed_at": t.closed_at.isoformat(),
            }
            for t in reversed(trades)
        ]

    def get_daily_pnl(self) -> float:
        """Retourne le PnL réalisé du jour en USD."""
        return self._realized_pnl_today

    def get_daily_pnl_pct(self) -> float:
        """Retourne le PnL réalisé du jour en pourcentage du capital."""
        if self._initial_capital <= 0:
            return 0.0
        return (self._realized_pnl_today / self._initial_capital) * 100

    def get_current_equity(self) -> float:
        """Retourne l'équity courante (capital + PnL réalisé)."""
        return self._current_equity

    def get_summary(self) -> dict:
        """Retourne un résumé du portefeuille pour le dashboard."""
        total_equity = (
            self._equity_history[-1].equity
            if self._equity_history
            else self._current_equity
        )
        return {
            "initial_capital": self._initial_capital,
            "current_equity": round(total_equity, 2),
            "total_pnl": round(self._total_realized_pnl, 2),
            "total_pnl_pct": round(
                (self._total_realized_pnl / self._initial_capital * 100)
                if self._initial_capital > 0
                else 0,
                2,
            ),
            "daily_pnl": round(self._realized_pnl_today, 2),
            "daily_pnl_pct": round(self.get_daily_pnl_pct(), 2),
            "total_trades": len(self._trade_history),
            "paper_mode": self.paper_mode,
        }

    def _fetch_live_equity(self) -> Optional[float]:
        """Récupère l'équity en temps réel depuis l'exchange."""
        state = self.client.get_user_state()
        if not state:
            return None

        try:
            margin_summary = state.get("marginSummary", {})
            return float(margin_summary.get("accountValue", 0))
        except (KeyError, ValueError, TypeError) as exc:
            logger.error(f"Erreur extraction équity live: {exc}")
            return None
