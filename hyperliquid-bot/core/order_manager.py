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

    # Minimum order sizes and decimal precision per asset on Hyperliquid
    SIZE_DECIMALS: dict[str, int] = {
        "BTC": 4,
        "ETH": 3,
        "SOL": 1,
        "XRP": 0,
        "IO": 0,
        "DOGE": 0,
        "AVAX": 1,
        "MATIC": 0,
        "ARB": 0,
        "OP": 1,
        "SUI": 1,
        "LINK": 1,
        "PEPE": 0,
        "kPEPE": 0,
        "HYPE": 1,
        "WIF": 0,
    }
    MIN_ORDER_VALUE = 10.0  # Minimum $10 order

    def _round_size(self, symbol: str, size: float, price: float) -> float:
        """Round order size to valid precision for Hyperliquid."""
        size = float(size)
        price = float(price)
        decimals = self.SIZE_DECIMALS.get(symbol, 2)
        rounded = round(size, decimals)

        # Ensure minimum order value
        if rounded * price < self.MIN_ORDER_VALUE:
            rounded = round(self.MIN_ORDER_VALUE / price, decimals)

        # Floor to avoid exceeding balance
        factor = 10 ** decimals
        rounded = int(rounded * factor) / factor

        return rounded

    def place_order(self, order: Order) -> Order:
        """Place an order on the exchange or simulate in paper mode."""
        # Get price for size validation
        mids = self._client.get_all_mids() if self._client.is_connected else {}
        price = float(mids.get(order.symbol, 0)) or 1.0

        # Round size to valid precision
        order.size = self._round_size(order.symbol, order.size, price)

        if order.size <= 0:
            order.status = OrderStatus.REJECTED
            logger.warning(f"Order size too small for {order.symbol}")
            return order

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

    def place_trigger_order(
        self, symbol: str, is_buy: bool, size: float,
        trigger_price: float, tpsl: str, reduce_only: bool = True
    ) -> Optional[str]:
        """Place a trigger order (TP or SL) on Hyperliquid."""
        trigger_price = float(trigger_price)
        size = float(size)

        if self._paper_mode:
            fake_id = f"paper_{tpsl}_{str(uuid.uuid4())[:6]}"
            logger.info(
                f"[PAPER] {tpsl.upper()} trigger order placed: "
                f"{symbol} {'BUY' if is_buy else 'SELL'} "
                f"size={size} trigger={trigger_price}"
            )
            return fake_id

        exchange = self._client.exchange
        if not exchange:
            logger.error("No exchange connection - cannot place trigger order")
            return None

        try:
            # Round size
            mids = self._client.get_all_mids() if self._client.is_connected else {}
            price = float(mids.get(symbol, trigger_price))
            size = self._round_size(symbol, size, price)
            if size <= 0:
                return None

            order_type = {
                "trigger": {
                    "triggerPx": str(round(trigger_price, 2)),
                    "isMarket": True,
                    "tpsl": tpsl,
                }
            }

            result = exchange.order(
                symbol, is_buy, size, trigger_price,
                order_type, reduce_only=reduce_only,
            )

            if result.get("status") == "ok":
                statuses = (
                    result.get("response", {})
                    .get("data", {})
                    .get("statuses", [])
                )
                if statuses and "resting" in statuses[0]:
                    oid = str(statuses[0]["resting"]["oid"])
                    logger.info(
                        f"{tpsl.upper()} order placed on exchange: "
                        f"{symbol} trigger={trigger_price} oid={oid}"
                    )
                    return oid
                # Some trigger orders return differently
                logger.info(
                    f"{tpsl.upper()} order submitted: {symbol} "
                    f"trigger={trigger_price}"
                )
                return "submitted"
            else:
                logger.error(f"Trigger order failed: {result}")
                return None

        except Exception as e:
            logger.error(f"Failed to place {tpsl} order: {e}")
            return None

    def place_tp_sl(
        self, symbol: str, side: OrderSide, size: float,
        stop_loss: Optional[float], take_profit: Optional[float],
    ) -> tuple[Optional[str], Optional[str]]:
        """Place both TP and SL trigger orders for a position.

        Args:
            symbol: Trading pair.
            side: Position side (BUY = long, SELL = short).
            size: Position size.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.

        Returns:
            Tuple of (sl_order_id, tp_order_id).
        """
        # For a long position, TP/SL are SELL orders (to close)
        # For a short position, TP/SL are BUY orders (to close)
        close_is_buy = side == OrderSide.SELL

        sl_oid = None
        tp_oid = None

        if stop_loss:
            sl_oid = self.place_trigger_order(
                symbol, close_is_buy, size, stop_loss, "sl"
            )

        if take_profit:
            tp_oid = self.place_trigger_order(
                symbol, close_is_buy, size, take_profit, "tp"
            )

        return sl_oid, tp_oid

    def cancel_trigger_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a trigger order on the exchange."""
        if self._paper_mode:
            logger.info(f"[PAPER] Trigger order cancelled: {order_id}")
            return True

        if not self._client.exchange or not order_id or order_id == "submitted":
            return False

        try:
            result = self._client.exchange.cancel(symbol, int(order_id))
            if result.get("status") == "ok":
                logger.info(f"Trigger order cancelled: {order_id}")
                return True
            logger.warning(f"Cancel trigger order failed: {result}")
        except Exception as e:
            logger.error(f"Cancel trigger order error: {e}")
        return False

    def update_stop_loss(
        self, symbol: str, side: OrderSide, size: float,
        old_sl_oid: Optional[str], new_sl_price: float,
    ) -> Optional[str]:
        """Update a stop-loss by cancelling old and placing new."""
        if old_sl_oid:
            self.cancel_trigger_order(symbol, old_sl_oid)

        close_is_buy = side == OrderSide.SELL
        return self.place_trigger_order(
            symbol, close_is_buy, size, new_sl_price, "sl"
        )

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
