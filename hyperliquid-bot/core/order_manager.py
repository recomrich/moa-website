"""
Gestionnaire d'ordres — création, modification et annulation des ordres.

Fournit une interface unifiée pour les opérations d'ordres, avec support
du paper trading (simulation) et du live trading.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger

from core.client import HyperliquidClient


class OrderSide(Enum):
    """Côté de l'ordre."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Type d'ordre."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    """Statut de l'ordre."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Représente un ordre de trading."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reduce_only: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    exchange_order_id: Optional[int] = None
    strategy_name: Optional[str] = None
    is_paper: bool = True


class OrderManager:
    """
    Gestionnaire d'ordres pour Hyperliquid.

    Gère la création et le cycle de vie des ordres en mode paper et live.
    """

    def __init__(self, client: HyperliquidClient, paper_mode: bool = True) -> None:
        """
        Initialise le gestionnaire d'ordres.

        Args:
            client: Client Hyperliquid authentifié.
            paper_mode: True pour simulation, False pour trading réel.
        """
        self.client = client
        self.paper_mode = paper_mode
        self._open_orders: dict[str, Order] = {}
        logger.info(f"OrderManager initialisé — mode: {'paper' if paper_mode else 'LIVE'}")

    def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_name: Optional[str] = None,
        current_price: Optional[float] = None,
    ) -> Optional[Order]:
        """
        Crée un ordre market (exécution immédiate au prix du marché).

        Args:
            symbol: Symbole de l'actif.
            side: BUY ou SELL.
            size: Quantité à trader.
            stop_loss: Prix du stop-loss (optionnel).
            take_profit: Prix du take-profit (optionnel).
            strategy_name: Nom de la stratégie émettrice.
            current_price: Prix actuel (requis en paper mode).

        Returns:
            Objet Order créé ou None si échec.
        """
        order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            size=size,
            price=current_price or 0.0,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            is_paper=self.paper_mode,
        )

        if self.paper_mode:
            return self._execute_paper_order(order, current_price)

        return self._execute_live_market_order(order)

    def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_name: Optional[str] = None,
    ) -> Optional[Order]:
        """
        Crée un ordre limit.

        Args:
            symbol: Symbole de l'actif.
            side: BUY ou SELL.
            size: Quantité à trader.
            price: Prix limite.
            stop_loss: Prix du stop-loss.
            take_profit: Prix du take-profit.
            strategy_name: Nom de la stratégie émettrice.

        Returns:
            Objet Order créé ou None si échec.
        """
        order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            size=size,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_name=strategy_name,
            is_paper=self.paper_mode,
        )

        if self.paper_mode:
            return self._execute_paper_order(order, price)

        return self._execute_live_limit_order(order)

    def cancel_order(self, order_id: str) -> bool:
        """
        Annule un ordre ouvert.

        Args:
            order_id: Identifiant interne de l'ordre.

        Returns:
            True si annulé avec succès, False sinon.
        """
        order = self._open_orders.get(order_id)
        if not order:
            logger.warning(f"Ordre {order_id} non trouvé pour annulation.")
            return False

        if self.paper_mode:
            order.status = OrderStatus.CANCELLED
            del self._open_orders[order_id]
            logger.info(f"[PAPER] Ordre annulé: {order_id}")
            return True

        if order.exchange_order_id is None:
            logger.error(f"Ordre {order_id} n'a pas d'ID exchange pour annulation.")
            return False

        result = self.client.cancel_order(order.symbol, order.exchange_order_id)
        if result and result.get("status") == "ok":
            order.status = OrderStatus.CANCELLED
            del self._open_orders[order_id]
            logger.info(f"Ordre annulé: {order_id} (exchange id: {order.exchange_order_id})")
            return True

        logger.error(f"Échec annulation ordre {order_id}: {result}")
        return False

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Annule tous les ordres ouverts, optionnellement filtrés par symbole.

        Args:
            symbol: Si fourni, annule uniquement les ordres de ce symbole.

        Returns:
            Nombre d'ordres annulés.
        """
        orders_to_cancel = [
            o for o in self._open_orders.values()
            if symbol is None or o.symbol == symbol
        ]

        cancelled = 0
        for order in orders_to_cancel:
            if self.cancel_order(order.id):
                cancelled += 1

        return cancelled

    def get_open_orders(self, symbol: Optional[str] = None) -> list[Order]:
        """
        Retourne les ordres ouverts.

        Args:
            symbol: Filtre par symbole si fourni.

        Returns:
            Liste des ordres ouverts.
        """
        orders = list(self._open_orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def _execute_paper_order(
        self, order: Order, execution_price: Optional[float]
    ) -> Optional[Order]:
        """Simule l'exécution d'un ordre en mode paper trading."""
        if execution_price is None:
            logger.error("Prix d'exécution requis en mode paper.")
            return None

        order.status = OrderStatus.FILLED
        order.filled_size = order.size
        order.avg_fill_price = execution_price
        order.filled_at = datetime.utcnow()

        logger.info(
            f"[PAPER] Ordre exécuté — {order.side.value.upper()} {order.size} {order.symbol} "
            f"@ ${execution_price:.4f} | SL: {order.stop_loss} | TP: {order.take_profit}"
        )
        return order

    def _execute_live_market_order(self, order: Order) -> Optional[Order]:
        """Exécute un ordre market sur Hyperliquid en mode live."""
        is_buy = order.side == OrderSide.BUY
        order_type = {"market": {}}

        result = self.client.place_order(
            symbol=order.symbol,
            is_buy=is_buy,
            size=order.size,
            price=0,
            order_type=order_type,
            reduce_only=order.reduce_only,
        )

        return self._process_live_order_result(order, result)

    def _execute_live_limit_order(self, order: Order) -> Optional[Order]:
        """Exécute un ordre limit sur Hyperliquid en mode live."""
        is_buy = order.side == OrderSide.BUY
        order_type = {"limit": {"tif": "Gtc"}}

        result = self.client.place_order(
            symbol=order.symbol,
            is_buy=is_buy,
            size=order.size,
            price=order.price,
            order_type=order_type,
            reduce_only=order.reduce_only,
        )

        return self._process_live_order_result(order, result)

    def _process_live_order_result(
        self, order: Order, result: Optional[dict]
    ) -> Optional[Order]:
        """Traite le résultat d'un appel API d'ordre live."""
        if not result:
            order.status = OrderStatus.REJECTED
            logger.error(f"Ordre rejeté (résultat vide): {order.symbol} {order.side.value}")
            return None

        status = result.get("status", "")
        if status != "ok":
            order.status = OrderStatus.REJECTED
            logger.error(f"Ordre rejeté: {result}")
            return None

        response_data = result.get("response", {}).get("data", {})
        statuses = response_data.get("statuses", [{}])

        if statuses and "resting" in statuses[0]:
            order.exchange_order_id = statuses[0]["resting"].get("oid")
            order.status = OrderStatus.OPEN
            self._open_orders[order.id] = order
        elif statuses and "filled" in statuses[0]:
            fill = statuses[0]["filled"]
            order.exchange_order_id = fill.get("oid")
            order.status = OrderStatus.FILLED
            order.filled_size = float(fill.get("totalSz", order.size))
            order.avg_fill_price = float(fill.get("avgPx", order.price))
            order.filled_at = datetime.utcnow()

        logger.info(
            f"[LIVE] Ordre {order.status.value} — {order.side.value.upper()} "
            f"{order.size} {order.symbol} @ ${order.avg_fill_price:.4f}"
        )
        return order
