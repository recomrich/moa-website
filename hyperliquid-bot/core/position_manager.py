"""Position management - tracking and managing open positions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from core.order_manager import OrderSide


@dataclass
class Position:
    """Represents an open trading position."""

    symbol: str
    side: OrderSide
    size: float
    entry_price: float
    leverage: int = 1
    is_perp: bool = False
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    strategy_name: str = ""
    opened_at: float = field(default_factory=time.time)
    position_id: str = ""

    @property
    def pnl_pct(self) -> float:
        """Calculate PnL percentage."""
        if self.entry_price == 0:
            return 0.0
        if self.side == OrderSide.BUY:
            raw_pct = (self.unrealized_pnl / (self.entry_price * self.size)) * 100
        else:
            raw_pct = (self.unrealized_pnl / (self.entry_price * self.size)) * 100
        return round(raw_pct, 2)


class PositionManager:
    """Manages open positions and monitors stop-loss/take-profit."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._closed_positions: list[dict] = []

    def open_position(self, position: Position) -> None:
        """Register a new open position."""
        key = f"{position.symbol}_{position.strategy_name}"
        position.position_id = key
        self._positions[key] = position
        logger.info(
            f"Position opened: {position.symbol} {position.side.value} "
            f"size={position.size} entry={position.entry_price} "
            f"SL={position.stop_loss} TP={position.take_profit}"
        )

    def close_position(
        self, position_id: str, exit_price: float, reason: str = ""
    ) -> Optional[dict]:
        """Close a position and record the result."""
        position = self._positions.pop(position_id, None)
        if not position:
            logger.warning(f"Position not found: {position_id}")
            return None

        if position.side == OrderSide.BUY:
            pnl = (exit_price - position.entry_price) * position.size
        else:
            pnl = (position.entry_price - exit_price) * position.size

        pnl *= position.leverage

        result = {
            "symbol": position.symbol,
            "side": position.side.value,
            "size": position.size,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "pnl": round(pnl, 4),
            "pnl_pct": round(
                (pnl / (position.entry_price * position.size)) * 100, 2
            ),
            "leverage": position.leverage,
            "strategy": position.strategy_name,
            "reason": reason,
            "opened_at": position.opened_at,
            "closed_at": time.time(),
        }

        self._closed_positions.append(result)
        logger.info(
            f"Position closed: {position.symbol} PnL={pnl:+.4f} "
            f"({result['pnl_pct']:+.2f}%) reason={reason}"
        )
        return result

    def update_prices(self, prices: dict[str, float]) -> list[str]:
        """Update unrealized PnL and check SL/TP triggers.

        Returns list of position IDs that hit SL or TP.
        """
        triggered: list[str] = []

        for pos_id, pos in list(self._positions.items()):
            current_price = prices.get(pos.symbol)
            if current_price is None:
                continue

            if pos.side == OrderSide.BUY:
                pos.unrealized_pnl = (
                    (current_price - pos.entry_price) * pos.size * pos.leverage
                )
            else:
                pos.unrealized_pnl = (
                    (pos.entry_price - current_price) * pos.size * pos.leverage
                )

            # Check stop-loss
            if pos.stop_loss:
                if pos.side == OrderSide.BUY and current_price <= pos.stop_loss:
                    triggered.append(pos_id)
                    continue
                if pos.side == OrderSide.SELL and current_price >= pos.stop_loss:
                    triggered.append(pos_id)
                    continue

            # Check take-profit
            if pos.take_profit:
                if pos.side == OrderSide.BUY and current_price >= pos.take_profit:
                    triggered.append(pos_id)
                    continue
                if pos.side == OrderSide.SELL and current_price <= pos.take_profit:
                    triggered.append(pos_id)
                    continue

        return triggered

    def get_position(self, position_id: str) -> Optional[Position]:
        return self._positions.get(position_id)

    def get_all_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_closed_positions(self, limit: int = 50) -> list[dict]:
        return self._closed_positions[-limit:]

    @property
    def open_count(self) -> int:
        return len(self._positions)

    def get_total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    def sync_from_exchange(self, client: Any) -> None:
        """Sync positions from exchange state (for live mode)."""
        try:
            user_state = client.get_user_state()
            if not user_state:
                return

            positions = user_state.get("assetPositions", [])
            for pos_data in positions:
                position = pos_data.get("position", {})
                symbol = position.get("coin", "")
                size = float(position.get("szi", 0))
                if size == 0:
                    continue

                entry_price = float(position.get("entryPx", 0))
                leverage_data = position.get("leverage", {})
                leverage = int(leverage_data.get("value", 1))

                side = OrderSide.BUY if size > 0 else OrderSide.SELL
                key = f"{symbol}_exchange"

                if key not in self._positions:
                    self._positions[key] = Position(
                        symbol=symbol,
                        side=side,
                        size=abs(size),
                        entry_price=entry_price,
                        leverage=leverage,
                        is_perp=True,
                        strategy_name="exchange",
                    )
                    logger.info(f"Synced position from exchange: {symbol}")

        except Exception as e:
            logger.error(f"Failed to sync positions: {e}")
