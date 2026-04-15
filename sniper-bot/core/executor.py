"""Trade executor - places and manages sniper trades with pullback-aware SL/TP."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from core.scanner import SpikeSignal


@dataclass
class SniperTrade:
    """An active sniper trade."""
    trade_id: str
    symbol: str
    direction: str  # "pump" or "dump"
    side: str  # "buy" or "sell"
    size: float
    entry_price: float
    leverage: int
    stop_loss: float
    take_profit: float
    strength: int
    opened_at: float = field(default_factory=time.time)
    max_hold_seconds: int = 300  # 5 min max hold
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    status: str = "open"  # open, closed, expired

    @property
    def age_seconds(self) -> float:
        return time.time() - self.opened_at

    @property
    def is_expired(self) -> bool:
        return self.age_seconds > self.max_hold_seconds


# Decimal precision per asset on Hyperliquid
SIZE_DECIMALS: dict[str, int] = {
    "BTC": 4, "ETH": 3, "SOL": 1, "XRP": 0, "DOGE": 0,
    "AVAX": 1, "MATIC": 0, "ARB": 0, "OP": 1, "SUI": 1,
    "LINK": 1, "ADA": 0, "DOT": 1, "NEAR": 1, "APT": 1,
    "INJ": 1, "TIA": 1, "SEI": 0, "JUP": 0, "WIF": 0,
    "PEPE": 0, "BONK": 0, "SHIB": 0, "FET": 0, "RNDR": 1,
    "WLD": 0, "STRK": 0, "PYTH": 0, "JTO": 1, "ONDO": 0,
}
MIN_ORDER_VALUE = 10.0


def round_size(symbol: str, size: float, price: float) -> float:
    """Round order size to valid precision."""
    decimals = SIZE_DECIMALS.get(symbol, 2)
    rounded = round(size, decimals)

    if rounded * price < MIN_ORDER_VALUE:
        rounded = round(MIN_ORDER_VALUE / price, decimals)

    factor = 10 ** decimals
    rounded = int(rounded * factor) / factor
    return rounded


class TradeExecutor:
    """Executes and manages sniper trades."""

    def __init__(
        self,
        client: Any,
        paper_mode: bool = True,
        risk_per_trade_pct: float = 2.0,
        max_open_trades: int = 3,
        tp_pct: float = 2.0,
        sl_pct: float = 1.0,
        max_hold_minutes: int = 5,
    ) -> None:
        self._client = client
        self._paper_mode = paper_mode
        self._risk_pct = risk_per_trade_pct
        self._max_open = max_open_trades
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct
        self._max_hold = max_hold_minutes * 60
        self._capital = 0.0

        self._open_trades: dict[str, SniperTrade] = {}
        self._closed_trades: list[dict] = []
        self._total_pnl = 0.0

    def set_capital(self, capital: float) -> None:
        self._capital = capital

    @property
    def open_count(self) -> int:
        return len(self._open_trades)

    @property
    def can_trade(self) -> bool:
        return self.open_count < self._max_open and self._capital > 0

    def execute_signal(self, signal: SpikeSignal) -> Optional[SniperTrade]:
        """Execute a spike signal - open a sniper trade.

        When pullback data is available (spike_price + pullback_price),
        uses smart SL/TP placement:
        - SL just beyond the pullback extreme (logical level)
        - TP targeting the spike peak with minimum 2:1 risk/reward
        """
        if not self.can_trade:
            return None

        # Don't trade same symbol twice
        for t in self._open_trades.values():
            if t.symbol == signal.symbol:
                logger.debug(f"Already in trade for {signal.symbol}")
                return None

        # Direction: pump -> buy (ride momentum), dump -> sell (ride down)
        side = "buy" if signal.direction == "pump" else "sell"

        # Dynamic leverage based on signal strength
        if signal.strength >= 80:
            leverage = 20
        elif signal.strength >= 60:
            leverage = 15
        elif signal.strength >= 40:
            leverage = 10
        else:
            leverage = 5

        price = signal.price

        # --- Pullback-aware SL/TP (smart placement) ---
        if signal.pullback_price > 0 and signal.spike_price > 0:
            sl_buffer_pct = 0.15  # 0.15% buffer beyond pullback extreme

            if side == "buy":
                # SL just below the pullback low (with buffer)
                stop_loss = round(
                    signal.pullback_price * (1 - sl_buffer_pct / 100), 6
                )
                # TP: best of spike re-test or 2:1 R:R
                risk = price - stop_loss
                if risk <= 0:
                    return None
                rr_target = price + risk * 2.0
                spike_target = signal.spike_price
                take_profit = round(max(rr_target, spike_target), 6)
            else:
                # SL just above the pullback high (with buffer)
                stop_loss = round(
                    signal.pullback_price * (1 + sl_buffer_pct / 100), 6
                )
                # TP: best of spike re-test or 2:1 R:R
                risk = stop_loss - price
                if risk <= 0:
                    return None
                rr_target = price - risk * 2.0
                spike_target = signal.spike_price
                take_profit = round(min(rr_target, spike_target), 6)

            logger.info(
                f"Pullback SL/TP: {signal.symbol} "
                f"entry=${price:.4f} SL=${stop_loss:.4f} TP=${take_profit:.4f} "
                f"R:R={abs(take_profit - price) / abs(price - stop_loss):.1f}:1"
            )
        else:
            # Fallback: original fixed percentage SL/TP
            if signal.strength >= 70:
                tp_mult = 1.5
                sl_mult = 0.8
            else:
                tp_mult = 1.0
                sl_mult = 1.0

            tp_pct = self._tp_pct * tp_mult
            sl_pct = self._sl_pct * sl_mult

            if side == "buy":
                stop_loss = round(price * (1 - sl_pct / 100), 6)
                take_profit = round(price * (1 + tp_pct / 100), 6)
            else:
                stop_loss = round(price * (1 + sl_pct / 100), 6)
                take_profit = round(price * (1 - tp_pct / 100), 6)

        # Position size based on risk
        risk_amount = self._capital * (self._risk_pct / 100)
        price_risk = abs(price - stop_loss)
        if price_risk == 0:
            return None
        size = risk_amount / price_risk
        max_size = (self._capital * leverage) / price
        size = min(size, max_size)

        size = round_size(signal.symbol, size, price)
        if size <= 0:
            return None

        # Place the order
        fill_price = self._place_order(signal.symbol, side, size, leverage)
        if fill_price is None:
            return None

        # Place TP/SL on exchange
        sl_oid = self._place_trigger(
            signal.symbol, side, size, stop_loss, "sl"
        )
        tp_oid = self._place_trigger(
            signal.symbol, side, size, take_profit, "tp"
        )

        trade = SniperTrade(
            trade_id=str(uuid.uuid4())[:8],
            symbol=signal.symbol,
            direction=signal.direction,
            side=side,
            size=size,
            entry_price=fill_price,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strength=signal.strength,
            max_hold_seconds=self._max_hold,
            sl_order_id=sl_oid,
            tp_order_id=tp_oid,
        )

        self._open_trades[trade.trade_id] = trade

        logger.info(
            f"SNIPER TRADE OPENED: {signal.symbol} {side.upper()} "
            f"size={size} @ {fill_price} lev={leverage}x "
            f"SL={stop_loss} TP={take_profit} "
            f"(strength={signal.strength}%)"
        )

        return trade

    def _place_order(
        self, symbol: str, side: str, size: float, leverage: int
    ) -> Optional[float]:
        """Place a market order. Returns fill price."""
        if self._paper_mode:
            mids = self._client.get_all_mids()
            price = float(mids.get(symbol, 0))
            if price <= 0:
                return None
            slippage = 0.001  # 0.1% simulated slippage
            if side == "buy":
                fill = price * (1 + slippage)
            else:
                fill = price * (1 - slippage)
            logger.info(f"[PAPER] {side.upper()} {symbol} size={size} @ {fill:.4f}")
            return fill

        exchange = self._client.exchange
        if not exchange:
            logger.error("No exchange connection")
            return None

        try:
            is_buy = side == "buy"
            result = exchange.market_open(symbol, is_buy, size, None)

            if result.get("status") == "ok":
                statuses = (
                    result.get("response", {})
                    .get("data", {})
                    .get("statuses", [])
                )
                if statuses and "filled" in statuses[0]:
                    fill_price = float(statuses[0]["filled"]["avgPx"])
                    return fill_price

            logger.error(f"Order failed: {result}")
            return None

        except Exception as e:
            logger.error(f"Order error: {e}")
            return None

    def _place_trigger(
        self, symbol: str, side: str, size: float,
        trigger_price: float, tpsl: str,
    ) -> Optional[str]:
        """Place a TP or SL trigger order."""
        if self._paper_mode:
            return f"paper_{tpsl}_{uuid.uuid4().hex[:6]}"

        exchange = self._client.exchange
        if not exchange:
            return None

        try:
            close_is_buy = side == "sell"
            size = round_size(symbol, size, trigger_price)

            order_type = {
                "trigger": {
                    "triggerPx": str(round(trigger_price, 2)),
                    "isMarket": True,
                    "tpsl": tpsl,
                }
            }

            result = exchange.order(
                symbol, close_is_buy, size, trigger_price,
                order_type, reduce_only=True,
            )

            if result.get("status") == "ok":
                statuses = (
                    result.get("response", {})
                    .get("data", {})
                    .get("statuses", [])
                )
                if statuses and "resting" in statuses[0]:
                    return str(statuses[0]["resting"]["oid"])
                return "submitted"

            return None
        except Exception as e:
            logger.error(f"Trigger order error ({tpsl}): {e}")
            return None

    def _cancel_trigger(self, symbol: str, order_id: Optional[str]) -> None:
        """Cancel a trigger order."""
        if not order_id or self._paper_mode or order_id == "submitted":
            return
        try:
            if self._client.exchange:
                self._client.exchange.cancel(symbol, int(order_id))
        except Exception:
            pass

    def update_trades(self, mids: dict[str, str]) -> list[dict]:
        """Check open trades for TP/SL/expiry. Returns list of closed trades."""
        closed_this_tick: list[dict] = []

        for trade_id, trade in list(self._open_trades.items()):
            price_str = mids.get(trade.symbol)
            if not price_str:
                continue

            current_price = float(price_str)

            # Check expiry (max hold time)
            if trade.is_expired:
                result = self._close_trade(trade, current_price, "expired")
                closed_this_tick.append(result)
                continue

            # Check SL
            if trade.side == "buy" and current_price <= trade.stop_loss:
                result = self._close_trade(trade, current_price, "stop_loss")
                closed_this_tick.append(result)
                continue
            if trade.side == "sell" and current_price >= trade.stop_loss:
                result = self._close_trade(trade, current_price, "stop_loss")
                closed_this_tick.append(result)
                continue

            # Check TP
            if trade.side == "buy" and current_price >= trade.take_profit:
                result = self._close_trade(trade, current_price, "take_profit")
                closed_this_tick.append(result)
                continue
            if trade.side == "sell" and current_price <= trade.take_profit:
                result = self._close_trade(trade, current_price, "take_profit")
                closed_this_tick.append(result)
                continue

        return closed_this_tick

    def _close_trade(
        self, trade: SniperTrade, exit_price: float, reason: str
    ) -> dict:
        """Close a trade and record result."""
        # Cancel remaining trigger orders
        self._cancel_trigger(trade.symbol, trade.sl_order_id)
        self._cancel_trigger(trade.symbol, trade.tp_order_id)

        # Close on exchange (live mode)
        if not self._paper_mode and self._client.exchange:
            try:
                is_buy = trade.side == "sell"  # opposite to close
                self._client.exchange.market_open(
                    trade.symbol, is_buy, trade.size, None
                )
            except Exception as e:
                logger.error(f"Close order error: {e}")

        # Calculate PnL
        if trade.side == "buy":
            pnl = (exit_price - trade.entry_price) * trade.size * trade.leverage
        else:
            pnl = (trade.entry_price - exit_price) * trade.size * trade.leverage

        pnl_pct = (pnl / (trade.entry_price * trade.size)) * 100

        self._total_pnl += pnl

        result = {
            "trade_id": trade.trade_id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "side": trade.side,
            "size": trade.size,
            "entry_price": trade.entry_price,
            "exit_price": exit_price,
            "leverage": trade.leverage,
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
            "strength": trade.strength,
            "hold_time": round(trade.age_seconds, 1),
            "closed_at": time.time(),
        }

        self._open_trades.pop(trade.trade_id, None)
        self._closed_trades.append(result)

        emoji = "WIN" if pnl > 0 else "LOSS"
        logger.info(
            f"TRADE CLOSED [{emoji}]: {trade.symbol} {trade.side} "
            f"PnL={pnl:+.4f} ({pnl_pct:+.2f}%) "
            f"reason={reason} hold={trade.age_seconds:.0f}s"
        )

        return result

    def get_open_trades(self) -> list[SniperTrade]:
        return list(self._open_trades.values())

    def get_closed_trades(self, limit: int = 100) -> list[dict]:
        return self._closed_trades[-limit:]

    def get_stats(self) -> dict:
        """Get trading statistics."""
        total = len(self._closed_trades)
        wins = sum(1 for t in self._closed_trades if t["pnl"] > 0)
        losses = total - wins

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
            "total_pnl": round(self._total_pnl, 4),
            "open_trades": self.open_count,
            "avg_hold_time": round(
                sum(t["hold_time"] for t in self._closed_trades) / total
                if total > 0 else 0, 1
            ),
        }
