"""
Gestionnaire de positions — suivi des positions ouvertes et calcul du PnL.

Maintient l'état des positions ouvertes, surveille les SL/TP et calcule
les performances en temps réel.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger

from core.client import HyperliquidClient
from core.order_manager import Order, OrderManager, OrderSide, OrderType


class PositionSide(Enum):
    """Côté d'une position."""
    LONG = "long"
    SHORT = "short"


@dataclass
class Position:
    """Représente une position ouverte."""
    id: str
    symbol: str
    side: PositionSide
    size: float
    entry_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    leverage: float = 1.0
    strategy_name: Optional[str] = None
    opened_at: datetime = field(default_factory=datetime.utcnow)
    is_paper: bool = True

    @property
    def unrealized_pnl(self) -> float:
        """PnL non réalisé en USD."""
        if self.side == PositionSide.LONG:
            return (self.current_price - self.entry_price) * self.size
        return (self.entry_price - self.current_price) * self.size

    @property
    def unrealized_pnl_pct(self) -> float:
        """PnL non réalisé en pourcentage."""
        if self.entry_price == 0:
            return 0.0
        notional = self.entry_price * self.size
        return (self.unrealized_pnl / notional) * 100 if notional > 0 else 0.0

    @property
    def notional_value(self) -> float:
        """Valeur notionnelle de la position en USD."""
        return self.size * self.current_price

    def is_sl_triggered(self) -> bool:
        """Vérifie si le stop-loss est déclenché."""
        if self.stop_loss is None:
            return False
        if self.side == PositionSide.LONG:
            return self.current_price <= self.stop_loss
        return self.current_price >= self.stop_loss

    def is_tp_triggered(self) -> bool:
        """Vérifie si le take-profit est déclenché."""
        if self.take_profit is None:
            return False
        if self.side == PositionSide.LONG:
            return self.current_price >= self.take_profit
        return self.current_price <= self.take_profit


class PositionManager:
    """
    Gestionnaire des positions ouvertes.

    Surveille les positions actives, met à jour les prix en temps réel
    et gère les fermetures automatiques (SL/TP).
    """

    def __init__(
        self,
        client: HyperliquidClient,
        order_manager: OrderManager,
        paper_mode: bool = True,
    ) -> None:
        """
        Initialise le gestionnaire de positions.

        Args:
            client: Client Hyperliquid authentifié.
            order_manager: Gestionnaire d'ordres.
            paper_mode: True pour simulation, False pour trading réel.
        """
        self.client = client
        self.order_manager = order_manager
        self.paper_mode = paper_mode
        self._positions: dict[str, Position] = {}
        logger.info("PositionManager initialisé.")

    def open_position(
        self,
        order: Order,
        leverage: float = 1.0,
    ) -> Optional[Position]:
        """
        Ouvre une position à partir d'un ordre exécuté.

        Args:
            order: Ordre exécuté (status FILLED).
            leverage: Levier appliqué à la position.

        Returns:
            Objet Position créé ou None si l'ordre n'est pas rempli.
        """
        if order.filled_size == 0 or order.avg_fill_price == 0:
            logger.error(f"Impossible d'ouvrir position: ordre non rempli {order.id}")
            return None

        side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT

        position = Position(
            id=order.id,
            symbol=order.symbol,
            side=side,
            size=order.filled_size,
            entry_price=order.avg_fill_price,
            current_price=order.avg_fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            leverage=leverage,
            strategy_name=order.strategy_name,
            is_paper=self.paper_mode,
        )

        self._positions[position.id] = position
        logger.info(
            f"Position ouverte: {side.value.upper()} {order.filled_size} {order.symbol} "
            f"@ ${order.avg_fill_price:.4f} | SL: {order.stop_loss} | TP: {order.take_profit}"
        )
        return position

    def close_position(
        self,
        position_id: str,
        current_price: float,
        reason: str = "manual",
    ) -> Optional[float]:
        """
        Ferme une position ouverte.

        Args:
            position_id: Identifiant de la position.
            current_price: Prix de fermeture.
            reason: Raison de fermeture ("manual", "sl", "tp", "strategy").

        Returns:
            PnL réalisé en USD ou None si position introuvable.
        """
        position = self._positions.get(position_id)
        if not position:
            logger.warning(f"Position {position_id} introuvable pour fermeture.")
            return None

        position.current_price = current_price
        realized_pnl = position.unrealized_pnl

        if not self.paper_mode:
            close_side = (
                OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
            )
            self.order_manager.create_market_order(
                symbol=position.symbol,
                side=close_side,
                size=position.size,
                current_price=current_price,
                strategy_name=position.strategy_name,
            )

        del self._positions[position_id]
        logger.info(
            f"Position fermée [{reason}]: {position.symbol} | "
            f"PnL: ${realized_pnl:+.2f} ({position.unrealized_pnl_pct:+.2f}%)"
        )
        return realized_pnl

    def update_prices(self, prices: dict[str, float]) -> list[tuple[str, float, str]]:
        """
        Met à jour les prix courants et vérifie les déclencheurs SL/TP.

        Args:
            prices: Dictionnaire {symbol: current_price}.

        Returns:
            Liste de (position_id, pnl, reason) pour les positions fermées.
        """
        closed_positions = []

        for pos_id, position in list(self._positions.items()):
            price = prices.get(position.symbol)
            if price is None:
                continue

            position.current_price = price

            if position.is_sl_triggered():
                pnl = self.close_position(pos_id, price, reason="sl")
                if pnl is not None:
                    closed_positions.append((pos_id, pnl, "sl"))
            elif position.is_tp_triggered():
                pnl = self.close_position(pos_id, price, reason="tp")
                if pnl is not None:
                    closed_positions.append((pos_id, pnl, "tp"))

        return closed_positions

    def get_positions(self, symbol: Optional[str] = None) -> list[Position]:
        """
        Retourne les positions ouvertes.

        Args:
            symbol: Filtre par symbole si fourni.

        Returns:
            Liste des positions ouvertes.
        """
        positions = list(self._positions.values())
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        return positions

    def get_position(self, position_id: str) -> Optional[Position]:
        """Retourne une position par son ID."""
        return self._positions.get(position_id)

    def get_total_unrealized_pnl(self) -> float:
        """Calcule le PnL non réalisé total de toutes les positions."""
        return sum(p.unrealized_pnl for p in self._positions.values())

    def get_positions_count(self) -> int:
        """Retourne le nombre de positions ouvertes."""
        return len(self._positions)

    def sync_with_exchange(self) -> None:
        """
        Synchronise les positions avec l'état réel de l'exchange (mode live uniquement).
        """
        if self.paper_mode:
            return

        state = self.client.get_user_state()
        if not state:
            logger.error("Impossible de synchroniser les positions avec l'exchange.")
            return

        exchange_positions = {}
        for pos_data in state.get("assetPositions", []):
            pos = pos_data.get("position", {})
            symbol = pos.get("coin")
            size = float(pos.get("szi", 0))
            if symbol and size != 0:
                exchange_positions[symbol] = pos

        logger.debug(f"Positions exchange synchronisées: {list(exchange_positions.keys())}")

    def to_dict_list(self) -> list[dict]:
        """Sérialise les positions pour le dashboard."""
        result = []
        for pos in self._positions.values():
            result.append({
                "id": pos.id,
                "symbol": pos.symbol,
                "side": pos.side.value,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": round(pos.unrealized_pnl, 4),
                "unrealized_pnl_pct": round(pos.unrealized_pnl_pct, 2),
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "leverage": pos.leverage,
                "strategy": pos.strategy_name,
                "opened_at": pos.opened_at.isoformat(),
            })
        return result
