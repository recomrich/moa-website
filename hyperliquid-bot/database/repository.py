"""
Repository — fonctions CRUD pour la base de données.

Fournit une interface de haut niveau pour persister et interroger
les données de trading (trades, ordres, signaux, équity).
"""

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from database.models import EquitySnapshot, Order, StrategyRun, Trade, get_engine


class TradingRepository:
    """
    Repository centralisant toutes les opérations de base de données.

    Utilise SQLAlchemy pour persister l'historique complet du bot.
    """

    def __init__(self, db_url: Optional[str] = None) -> None:
        """
        Initialise le repository.

        Args:
            db_url: URL SQLite (défaut: models.DATABASE_URL).
        """
        from database.models import DATABASE_URL, create_all_tables
        url = db_url or DATABASE_URL
        create_all_tables(url)
        self._engine = get_engine(url)
        logger.info(f"Repository initialisé — DB: {url}")

    def save_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        strategy_name: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        leverage: float = 1.0,
        market_type: str = "perps",
        is_paper: bool = True,
    ) -> Trade:
        """
        Persiste un nouveau trade ouvert.

        Returns:
            Objet Trade créé.
        """
        trade = Trade(
            id=trade_id,
            symbol=symbol,
            side=side,
            market_type=market_type,
            entry_price=entry_price,
            size=size,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            is_paper=is_paper,
            opened_at=datetime.utcnow(),
        )

        with Session(self._engine) as session:
            session.merge(trade)
            session.commit()

        return trade

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        pnl: float,
        close_reason: str,
    ) -> Optional[Trade]:
        """
        Met à jour un trade avec les données de fermeture.

        Args:
            trade_id: ID du trade.
            exit_price: Prix de sortie.
            pnl: PnL réalisé.
            close_reason: Raison de fermeture.

        Returns:
            Trade mis à jour ou None si introuvable.
        """
        with Session(self._engine) as session:
            trade = session.get(Trade, trade_id)
            if not trade:
                logger.warning(f"Trade {trade_id} introuvable en DB.")
                return None

            now = datetime.utcnow()
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.close_reason = close_reason
            trade.closed_at = now

            if trade.opened_at:
                trade.duration_seconds = (now - trade.opened_at).total_seconds()

            notional = trade.entry_price * trade.size
            trade.pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0

            session.commit()
            session.refresh(trade)
            return trade

    def save_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: float,
        status: str,
        strategy_name: Optional[str] = None,
        is_paper: bool = True,
        filled_size: float = 0.0,
        avg_fill_price: float = 0.0,
        exchange_order_id: Optional[int] = None,
    ) -> None:
        """Persiste un ordre."""
        order = Order(
            id=order_id,
            exchange_order_id=exchange_order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            filled_size=filled_size,
            avg_fill_price=avg_fill_price,
            status=status,
            strategy_name=strategy_name,
            is_paper=is_paper,
        )

        with Session(self._engine) as session:
            session.merge(order)
            session.commit()

    def save_strategy_run(
        self,
        strategy_name: str,
        symbol: str,
        timeframe: str,
        signal: str,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        confidence: float = 1.0,
        reason: str = "",
        acted_upon: bool = False,
    ) -> None:
        """Persiste un signal de stratégie."""
        run = StrategyRun(
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            reason=reason,
            acted_upon=acted_upon,
        )

        with Session(self._engine) as session:
            session.add(run)
            session.commit()

    def save_equity_snapshot(
        self,
        equity: float,
        unrealized_pnl: float = 0.0,
        realized_pnl_today: float = 0.0,
        open_positions: int = 0,
        is_paper: bool = True,
    ) -> None:
        """Persiste un instantané de l'équity."""
        snapshot = EquitySnapshot(
            equity=equity,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=realized_pnl_today,
            open_positions=open_positions,
            is_paper=is_paper,
        )

        with Session(self._engine) as session:
            session.add(snapshot)
            session.commit()

    def get_recent_trades(self, limit: int = 50, symbol: Optional[str] = None) -> list[dict]:
        """
        Récupère les trades récents.

        Args:
            limit: Nombre max de trades.
            symbol: Filtre par symbole.

        Returns:
            Liste de dictionnaires.
        """
        with Session(self._engine) as session:
            query = session.query(Trade).filter(Trade.closed_at.isnot(None))
            if symbol:
                query = query.filter(Trade.symbol == symbol)
            trades = query.order_by(desc(Trade.closed_at)).limit(limit).all()
            return [self._trade_to_dict(t) for t in trades]

    def get_strategy_stats(self, strategy_name: str) -> dict:
        """
        Calcule les statistiques de performance d'une stratégie.

        Args:
            strategy_name: Nom de la stratégie.

        Returns:
            Dictionnaire de statistiques.
        """
        with Session(self._engine) as session:
            trades = (
                session.query(Trade)
                .filter(
                    Trade.strategy_name == strategy_name,
                    Trade.closed_at.isnot(None),
                )
                .all()
            )

            if not trades:
                return {"strategy": strategy_name, "total_trades": 0}

            winning = [t for t in trades if t.pnl and t.pnl > 0]
            total_pnl = sum(t.pnl or 0 for t in trades)

            return {
                "strategy": strategy_name,
                "total_trades": len(trades),
                "winning_trades": len(winning),
                "win_rate": round(len(winning) / len(trades) * 100, 1),
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / len(trades), 4),
            }

    def get_equity_history(self, hours: int = 24) -> list[dict]:
        """
        Récupère l'historique d'équity sur N heures.

        Args:
            hours: Nombre d'heures d'historique.

        Returns:
            Liste de points d'équity.
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        with Session(self._engine) as session:
            snapshots = (
                session.query(EquitySnapshot)
                .filter(EquitySnapshot.recorded_at >= since)
                .order_by(EquitySnapshot.recorded_at)
                .all()
            )
            return [
                {
                    "timestamp": s.recorded_at.isoformat(),
                    "equity": s.equity,
                    "unrealized_pnl": s.unrealized_pnl,
                    "realized_pnl_today": s.realized_pnl_today,
                }
                for s in snapshots
            ]

    def _trade_to_dict(self, trade: Trade) -> dict:
        """Sérialise un objet Trade en dictionnaire."""
        return {
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "size": trade.size,
            "pnl": round(trade.pnl or 0, 4),
            "pnl_pct": round(trade.pnl_pct or 0, 3),
            "strategy": trade.strategy_name,
            "close_reason": trade.close_reason,
            "duration_min": round((trade.duration_seconds or 0) / 60, 1),
            "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
            "is_paper": trade.is_paper,
        }
