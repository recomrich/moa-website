"""Order management - creation, modification, and cancellation of orders."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from loguru import logger


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Represents a trading order."""

    symbol: str
    side: OrderSide
    size: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    leverage: int = 1
    is_perp: bool = False
    status: OrderStatus = OrderStatus.PENDING
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    exchange_order_id: Optional[str] = None
    fill_price: Optional[float] = None
    filled_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)


class OrderManager:
    """Manages order lifecycle on Hyperliquid."""

    def __init__(self, client: Any, paper_mode: bool = True) -> None:
        self._client = client
        self._paper_mode = paper_mode
        self._pending_orders: dict[str, Order] = {}
        self._filled_orders: list[Order] = []

    def place_order(self, order: Order) -> Order:
        """Place an order on the exchange or simulate in paper mode."""
        logger.info(
            f"{'[PAPER] ' if self._paper_mode else ''}"
            f"Placing {order.side.value} {order.order_type.value} order: "
            f"{order.symbol} size={order.size}"
            f"{f' price={order.price}' if order.price else ''}"
        )

        if self._paper_mode:
            return self._simulate_order(order)

        return self._execute_live_order(order)

    def _simulate_order(self, order: Order) -> Order:
        """Simulate order fill in paper trading mode."""
        mids = self._client.get_all_mids() if self._client.is_connected else {}
        mid_price = float(mids.get(order.symbol, 0))

        if order.order_type == OrderType.MARKET and mid_price > 0:
            slippage = 0.0005  # 0.05% simulated slippage
            if order.side == OrderSide.BUY:
                order.fill_price = mid_price * (1 + slippage)
            else:
                order.fill_price = mid_price * (1 - slippage)
        elif order.price:
            order.fill_price = order.price
        else:
            order.fill_price = mid_price if mid_price > 0 else None

        if order.fill_price:
            order.status = OrderStatus.FILLED
            order.filled_at = time.time()
            self._filled_orders.append(order)
            logger.info(
                f"[PAPER] Order filled: {order.symbol} "
                f"{order.side.value} @ {order.fill_price}"
            )
        else:
            order.status = OrderStatus.REJECTED
            logger.warning(f"[PAPER] Order rejected - no price available for {order.symbol}")

        return order

    def _execute_live_order(self, order: Order) -> Order:
        """Execute a real order on Hyperliquid."""
        exchange = self._client.exchange
        if not exchange:
            order.status = OrderStatus.REJECTED
            logger.error("No exchange connection available")
            return order

        try:
            is_buy = order.side == OrderSide.BUY

            if order.order_type == OrderType.MARKET:
                result = exchange.market_open(
                    order.symbol, is_buy, order.size, None
                )
            else:
                result = exchange.order(
                    order.symbol, is_buy, order.size,
                    order.price, {"limit": {"tif": "Gtc"}}
                )

            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses:
                    status_data = statuses[0]
                    if "filled" in status_data:
                        order.status = OrderStatus.FILLED
                        order.fill_price = float(status_data["filled"]["avgPx"])
                        order.exchange_order_id = str(
                            status_data["filled"]["oid"]
                        )
                        order.filled_at = time.time()
                        self._filled_orders.append(order)
                    elif "resting" in status_data:
                        order.status = OrderStatus.PENDING
                        order.exchange_order_id = str(
                            status_data["resting"]["oid"]
                        )
                        self._pending_orders[order.order_id] = order
                    else:
                        order.status = OrderStatus.REJECTED
                        logger.warning(f"Order rejected: {status_data}")
            else:
                order.status = OrderStatus.REJECTED
                logger.error(f"Order failed: {result}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            logger.error(f"Order execution error: {e}")

        return order

    def cancel_order(self, order: Order) -> bool:
        """Cancel a pending order."""
        if self._paper_mode:
            order.status = OrderStatus.CANCELLED
            self._pending_orders.pop(order.order_id, None)
            logger.info(f"[PAPER] Order cancelled: {order.order_id}")
            return True

        if not self._client.exchange or not order.exchange_order_id:
            return False

        try:
            result = self._client.exchange.cancel(
                order.symbol, int(order.exchange_order_id)
            )
            if result.get("status") == "ok":
                order.status = OrderStatus.CANCELLED
                self._pending_orders.pop(order.order_id, None)
                logger.info(f"Order cancelled: {order.exchange_order_id}")
                return True
        except Exception as e:
            logger.error(f"Cancel order error: {e}")
        return False

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all pending orders, optionally for a specific symbol."""
        cancelled = 0
        orders = list(self._pending_orders.values())
        for order in orders:
            if symbol and order.symbol != symbol:
                continue
            if self.cancel_order(order):
                cancelled += 1
        return cancelled

    def get_pending_orders(self) -> list[Order]:
        return list(self._pending_orders.values())

    def get_filled_orders(self, limit: int = 50) -> list[Order]:
        return self._filled_orders[-limit:]
