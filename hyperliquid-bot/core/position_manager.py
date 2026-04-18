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
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    peak_price: float = 0.0  # highest price seen for longs, lowest for shorts

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

    def __init__(
        self,
        max_per_symbol: int = 1,
        cooldown_minutes: int = 30,
        trailing_stop_pct: float = 1.5,
    ) -> None:
        self._positions: dict[str, Position] = {}
        self._closed_positions: list[dict] = []
        self._max_per_symbol = max_per_symbol
        self._cooldown_seconds = cooldown_minutes * 60
        self._trailing_stop_pct = trailing_stop_pct  # % sous le pic pour activer la sortie
        self._position_counter = 0
        self._last_trade_time: dict[str, float] = {}

    def _next_key(self, symbol: str, strategy_name: str) -> str:
        """Generate a unique position key."""
        self._position_counter += 1
        return f"{symbol}_{strategy_name}_{self._position_counter}"

    def open_position(self, position: Position) -> None:
        """Register a new open position."""
        key = self._next_key(position.symbol, position.strategy_name)
        position.position_id = key
        position.peak_price = position.entry_price
        self._positions[key] = position
        self._last_trade_time[position.symbol] = time.time()
        logger.info(
            f"Position opened: {position.symbol} {position.side.value} "
            f"size={position.size} entry={position.entry_price} "
            f"SL={position.stop_loss} TP={position.take_profit} "
            f"trailing={self._trailing_stop_pct}% "
            f"(id={key})"
        )

    def can_open_for_symbol(self, symbol: str, strategy_name: str = "") -> bool:
        """Check if we can open a new position for this symbol.

        Checks:
        1. Not exceeding max positions per symbol.
        2. GLOBAL cooldown since last trade on this symbol (any strategy).
        """
        symbol_count = sum(
            1 for p in self._positions.values() if p.symbol == symbol
        )
        if symbol_count >= self._max_per_symbol:
            return False

        now = time.time()
        last_trade = self._last_trade_time.get(symbol, 0)
        if (now - last_trade) < self._cooldown_seconds:
            return False

        return True

    def get_symbol_position_count(self, symbol: str) -> int:
        """Count open positions for a symbol."""
        return sum(1 for p in self._positions.values() if p.symbol == symbol)

    def close_position(
        self, position_id: str, exit_price: float, reason: str = ""
    ) -> Optional[dict]:
        """Close a position and record the result."""
        position = self._positions.pop(position_id, None)
        if not position:
            logger.warning(f"Position not found: {position_id}")
            return None

        # Cooldown redémarre à la fermeture (pas à l'ouverture)
        self._last_trade_time[position.symbol] = time.time()

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

    def update_prices(
        self, prices: dict[str, float]
    ) -> tuple[list[str], list[str]]:
        """Update unrealized PnL, trailing stops, and check SL/TP triggers.

        Returns:
            Tuple of (triggered_ids, sl_updated_ids).
            - triggered_ids: positions that hit SL or TP.
            - sl_updated_ids: positions whose trailing SL moved (need exchange update).
        """
        triggered: list[str] = []
        sl_updated: list[str] = []

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

            # Calculate profit percentage for this position
            if pos.entry_price > 0:
                if pos.side == OrderSide.BUY:
                    profit_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
                else:
                    profit_pct = ((pos.entry_price - current_price) / pos.entry_price) * 100
            else:
                profit_pct = 0.0

            # Emergency exit: close if leveraged loss exceeds 5%
            if profit_pct < 0 and abs(profit_pct) * pos.leverage >= 5.0:
                logger.warning(
                    f"Emergency exit {pos.symbol}: "
                    f"loss={abs(profit_pct) * pos.leverage:.1f}% (leveraged)"
                )
                triggered.append(pos_id)
                continue

            # Trailing stop: % fixe sous/sur le pic atteint, activé après 0.5% de profit
            # Exemple: trailing 1.5% -> si BTC monte à 80000, SL = 80000 * 0.985 = 78800
            if profit_pct >= 0.5 and self._trailing_stop_pct > 0:
                trail_mult = self._trailing_stop_pct / 100.0
                if pos.side == OrderSide.BUY:
                    # Mettre à jour le pic le plus haut atteint
                    if current_price > pos.peak_price:
                        pos.peak_price = current_price
                    # SL = pic - trailing%
                    trailing_sl = round(pos.peak_price * (1 - trail_mult), 6)
                    if pos.stop_loss is None or trailing_sl > pos.stop_loss:
                        old_sl = pos.stop_loss or 0
                        pos.stop_loss = trailing_sl
                        if old_sl > 0 and abs(trailing_sl - old_sl) / old_sl > 0.005:
                            sl_updated.append(pos_id)
                            logger.info(
                                f"Trailing SL {pos.symbol}: "
                                f"pic=${pos.peak_price:.2f} -> SL=${trailing_sl:.2f} "
                                f"({self._trailing_stop_pct}% sous le pic)"
                            )
                else:
                    # SHORT: on suit le prix le plus bas atteint
                    if pos.peak_price == pos.entry_price or current_price < pos.peak_price:
                        pos.peak_price = current_price
                    # SL = creux + trailing%
                    trailing_sl = round(pos.peak_price * (1 + trail_mult), 6)
                    if pos.stop_loss is None or trailing_sl < pos.stop_loss:
                        old_sl = pos.stop_loss or 0
                        pos.stop_loss = trailing_sl
                        if old_sl > 0 and abs(trailing_sl - old_sl) / old_sl > 0.005:
                            sl_updated.append(pos_id)
                            logger.info(
                                f"Trailing SL {pos.symbol}: "
                                f"creux=${pos.peak_price:.2f} -> SL=${trailing_sl:.2f} "
                                f"({self._trailing_stop_pct}% sur le creux)"
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

            # Time-based exit: close after 24h if not profitable
            age_hours = (time.time() - pos.opened_at) / 3600
            if age_hours >= 24 and profit_pct <= 0:
                logger.info(
                    f"Time exit {pos.symbol}: open {age_hours:.0f}h, "
                    f"PnL={profit_pct:.1f}%"
                )
                triggered.append(pos_id)
                continue

        return triggered, sl_updated

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
