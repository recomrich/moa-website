"""Price scanner - monitors ALL Hyperliquid assets for spikes with pullback confirmation.

Strategy: Instead of trading immediately when a spike is detected,
wait for a pullback (price retrace) and confirmation before entering.
This avoids buying at the top of a pump or selling at the bottom of a dump.

Flow:
1. Detect spike (pump or dump) -> create PendingPullback
2. Wait for price to retrace (pullback)
3. Confirm price resumes in spike direction (bounce)
4. THEN emit the signal for trading at a better price
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class PriceSnapshot:
    """A single price reading."""
    price: float
    timestamp: float


@dataclass
class SpikeSignal:
    """Detected spike opportunity (confirmed after pullback)."""
    symbol: str
    direction: str  # "pump" or "dump"
    price: float  # entry price (after pullback confirmation)
    change_pct_1m: float
    change_pct_5m: float
    change_pct_15m: float
    spread_pct: float
    strength: int  # 0-100 confidence score
    detected_at: float = field(default_factory=time.time)
    spike_price: float = 0.0  # peak/trough of the spike (for TP reference)
    pullback_price: float = 0.0  # extreme of the pullback (for SL reference)


@dataclass
class PendingPullback:
    """A spike waiting for pullback confirmation before trading."""
    symbol: str
    direction: str  # "pump" or "dump"
    spike_price: float  # peak (pump) or trough (dump) price
    detected_at: float
    strength: int
    change_pct_1m: float
    change_pct_5m: float
    change_pct_15m: float
    pullback_extreme: float = 0.0  # lowest (pump) or highest (dump) since spike
    pullback_reached: bool = False  # True once min pullback % is reached
    max_wait_seconds: float = 90.0


class PriceScanner:
    """Scans all Hyperliquid assets for unusual price movements.

    Keeps a rolling window of prices for every asset and detects:
    - Sudden price jumps (pump) or drops (dump)
    - Acceleration (move getting faster)

    Then waits for pullback confirmation before emitting a signal.
    """

    def __init__(
        self,
        min_spike_pct_1m: float = 1.5,
        min_spike_pct_5m: float = 3.0,
        min_spike_pct_15m: float = 5.0,
        history_minutes: int = 20,
        poll_interval: int = 3,
        blacklist: Optional[list[str]] = None,
        # Pullback parameters
        min_pullback_pct: float = 0.3,
        max_pullback_pct: float = 2.0,
        confirm_bounce_pct: float = 0.15,
        max_pullback_wait: float = 90.0,
    ) -> None:
        self._min_spike_1m = min_spike_pct_1m
        self._min_spike_5m = min_spike_pct_5m
        self._min_spike_15m = min_spike_pct_15m
        self._history_seconds = history_minutes * 60
        self._poll_interval = poll_interval
        self._blacklist = set(blacklist or [])

        # Pullback settings
        self._min_pullback_pct = min_pullback_pct
        self._max_pullback_pct = max_pullback_pct
        self._confirm_bounce_pct = confirm_bounce_pct
        self._max_pullback_wait = max_pullback_wait

        # Price history: symbol -> deque of PriceSnapshot
        self._history: dict[str, deque[PriceSnapshot]] = {}

        # Pending pullbacks: symbol -> PendingPullback
        self._pending_pullbacks: dict[str, PendingPullback] = {}

        # Track recently signaled symbols to avoid spam
        self._recent_signals: dict[str, float] = {}
        self._signal_cooldown = 300  # 5 min cooldown per symbol

    def update_prices(self, mids: dict[str, str]) -> list[SpikeSignal]:
        """Update all prices, detect spikes, and check pullbacks.

        Returns only CONFIRMED signals (after pullback) ready for trading.
        """
        now = time.time()

        for symbol, price_str in mids.items():
            if symbol in self._blacklist:
                continue

            try:
                price = float(price_str)
            except (ValueError, TypeError):
                continue

            if price <= 0:
                continue

            # Initialize history for new symbol
            if symbol not in self._history:
                self._history[symbol] = deque()

            history = self._history[symbol]
            history.append(PriceSnapshot(price=price, timestamp=now))

            # Clean old data
            cutoff = now - self._history_seconds
            while history and history[0].timestamp < cutoff:
                history.popleft()

            # Need at least ~30 seconds of data
            if len(history) < 5:
                continue

            # Skip if already watching this symbol for pullback
            if symbol in self._pending_pullbacks:
                continue

            # Calculate price changes over different windows
            change_1m = self._calc_change(history, now, 60)
            change_5m = self._calc_change(history, now, 300)
            change_15m = self._calc_change(history, now, 900)

            # Detect spike -> creates PendingPullback (NOT a signal yet)
            self._detect_spike(
                symbol, price, change_1m, change_5m, change_15m, now
            )

        # Check all pending pullbacks for confirmation
        confirmed_signals = self._check_pullbacks(mids, now)

        return confirmed_signals

    def _calc_change(
        self, history: deque[PriceSnapshot], now: float, window_seconds: int
    ) -> float:
        """Calculate percentage change over a time window."""
        target_time = now - window_seconds
        # Find the closest snapshot to target_time
        old_price = None
        for snap in history:
            if snap.timestamp <= target_time:
                old_price = snap.price
            else:
                break

        if old_price is None or old_price == 0:
            # Use oldest available
            if history:
                old_price = history[0].price
            else:
                return 0.0

        if old_price == 0:
            return 0.0

        current_price = history[-1].price
        return ((current_price - old_price) / old_price) * 100

    def _detect_spike(
        self,
        symbol: str,
        price: float,
        change_1m: float,
        change_5m: float,
        change_15m: float,
        now: float,
    ) -> None:
        """Check if price changes qualify as a spike.

        Instead of returning a signal immediately, creates a PendingPullback
        that must be confirmed by a price retrace + bounce.
        """

        # Check cooldown
        last_signal = self._recent_signals.get(symbol, 0)
        if now - last_signal < self._signal_cooldown:
            return

        # Determine if this is a pump or dump
        is_pump_1m = change_1m >= self._min_spike_1m
        is_dump_1m = change_1m <= -self._min_spike_1m
        is_pump_5m = change_5m >= self._min_spike_5m
        is_dump_5m = change_5m <= -self._min_spike_5m
        is_pump_15m = change_15m >= self._min_spike_15m
        is_dump_15m = change_15m <= -self._min_spike_15m

        # Need at least one timeframe to trigger
        if not any([
            is_pump_1m, is_dump_1m,
            is_pump_5m, is_dump_5m,
            is_pump_15m, is_dump_15m,
        ]):
            return

        # Determine direction - prefer shorter timeframe signals
        if is_pump_1m or is_pump_5m:
            direction = "pump"
        elif is_dump_1m or is_dump_5m:
            direction = "dump"
        elif is_pump_15m:
            direction = "pump"
        elif is_dump_15m:
            direction = "dump"
        else:
            return

        # Calculate strength (0-100)
        strength = self._calc_strength(
            change_1m, change_5m, change_15m, direction
        )

        # Mark cooldown so we don't re-detect the same spike
        self._recent_signals[symbol] = now

        # Create pending pullback (wait for confirmation before trading)
        self._pending_pullbacks[symbol] = PendingPullback(
            symbol=symbol,
            direction=direction,
            spike_price=price,
            detected_at=now,
            strength=strength,
            change_pct_1m=round(change_1m, 2),
            change_pct_5m=round(change_5m, 2),
            change_pct_15m=round(change_15m, 2),
            pullback_extreme=price,  # starts at spike price
            max_wait_seconds=self._max_pullback_wait,
        )

        logger.info(
            f"SPIKE DETECTED: {symbol} {direction.upper()} "
            f"1m={change_1m:+.2f}% 5m={change_5m:+.2f}% "
            f"15m={change_15m:+.2f}% strength={strength}% "
            f"-> Waiting for pullback..."
        )

    def _check_pullbacks(
        self, mids: dict[str, str], now: float
    ) -> list[SpikeSignal]:
        """Check all pending pullbacks for confirmation.

        For each pending pullback:
        - Phase 1: Wait for price to retrace at least min_pullback_pct
        - Phase 2: Wait for price to bounce back confirm_bounce_pct
        - Cancel if retrace exceeds max_pullback_pct or timeout
        """
        confirmed: list[SpikeSignal] = []
        expired: list[str] = []

        for symbol, pb in self._pending_pullbacks.items():
            price_str = mids.get(symbol)
            if not price_str:
                continue

            try:
                price = float(price_str)
            except (ValueError, TypeError):
                continue

            # Check timeout
            if now - pb.detected_at > pb.max_wait_seconds:
                expired.append(symbol)
                logger.debug(
                    f"Pullback timeout: {symbol} "
                    f"(no confirmation in {pb.max_wait_seconds:.0f}s)"
                )
                continue

            if pb.direction == "pump":
                signal = self._check_pump_pullback(pb, price, expired)
            else:
                signal = self._check_dump_pullback(pb, price, expired)

            if signal:
                confirmed.append(signal)

        # Cleanup expired/confirmed entries
        for symbol in expired:
            self._pending_pullbacks.pop(symbol, None)

        return confirmed

    def _check_pump_pullback(
        self, pb: PendingPullback, price: float, expired: list[str]
    ) -> Optional[SpikeSignal]:
        """Check pullback for a pump spike.

        Pump went UP -> wait for price to come DOWN (pullback)
        -> then bounce back UP (confirmation) -> emit signal to buy LONG.
        """
        # Track the lowest point since spike
        if price < pb.pullback_extreme:
            pb.pullback_extreme = price

        # How much has price retraced from spike peak?
        retrace_pct = (
            (pb.spike_price - pb.pullback_extreme) / pb.spike_price
        ) * 100

        # Phase 1: waiting for minimum pullback
        if not pb.pullback_reached:
            if retrace_pct >= self._min_pullback_pct:
                pb.pullback_reached = True
                logger.info(
                    f"PULLBACK DETECTED: {pb.symbol} dropped "
                    f"{retrace_pct:.2f}% from peak ${pb.spike_price:.4f}"
                )

        # Cancel if pullback is too deep (move completely reversed)
        if retrace_pct >= self._max_pullback_pct:
            expired.append(pb.symbol)
            logger.info(
                f"Pullback too deep ({retrace_pct:.1f}%), "
                f"signal cancelled: {pb.symbol}"
            )
            return None

        # Phase 2: after pullback reached, wait for bounce confirmation
        if pb.pullback_reached:
            bounce_pct = (
                (price - pb.pullback_extreme) / pb.pullback_extreme
            ) * 100

            if bounce_pct >= self._confirm_bounce_pct:
                # CONFIRMED! Price pulled back and bounced -> real move
                expired.append(pb.symbol)
                logger.info(
                    f"PULLBACK CONFIRMED: {pb.symbol} LONG "
                    f"spike=${pb.spike_price:.4f} "
                    f"low=${pb.pullback_extreme:.4f} "
                    f"entry=${price:.4f} bounce={bounce_pct:.2f}%"
                )
                return SpikeSignal(
                    symbol=pb.symbol,
                    direction="pump",
                    price=price,
                    change_pct_1m=pb.change_pct_1m,
                    change_pct_5m=pb.change_pct_5m,
                    change_pct_15m=pb.change_pct_15m,
                    spread_pct=0.0,
                    strength=min(pb.strength + 10, 100),
                    spike_price=pb.spike_price,
                    pullback_price=pb.pullback_extreme,
                )

        return None

    def _check_dump_pullback(
        self, pb: PendingPullback, price: float, expired: list[str]
    ) -> Optional[SpikeSignal]:
        """Check pullback for a dump spike.

        Dump went DOWN -> wait for price to come UP (pullback)
        -> then drop back DOWN (confirmation) -> emit signal to sell SHORT.
        """
        # Track the highest point since spike
        if price > pb.pullback_extreme:
            pb.pullback_extreme = price

        # How much has price bounced from spike trough?
        retrace_pct = (
            (pb.pullback_extreme - pb.spike_price) / pb.spike_price
        ) * 100

        # Phase 1: waiting for minimum pullback
        if not pb.pullback_reached:
            if retrace_pct >= self._min_pullback_pct:
                pb.pullback_reached = True
                logger.info(
                    f"PULLBACK DETECTED: {pb.symbol} bounced "
                    f"{retrace_pct:.2f}% from low ${pb.spike_price:.4f}"
                )

        # Cancel if pullback is too deep (move completely reversed)
        if retrace_pct >= self._max_pullback_pct:
            expired.append(pb.symbol)
            logger.info(
                f"Pullback too deep ({retrace_pct:.1f}%), "
                f"signal cancelled: {pb.symbol}"
            )
            return None

        # Phase 2: after pullback reached, wait for drop confirmation
        if pb.pullback_reached:
            drop_pct = (
                (pb.pullback_extreme - price) / pb.pullback_extreme
            ) * 100

            if drop_pct >= self._confirm_bounce_pct:
                # CONFIRMED! Price bounced and dropped again -> real move
                expired.append(pb.symbol)
                logger.info(
                    f"PULLBACK CONFIRMED: {pb.symbol} SHORT "
                    f"spike=${pb.spike_price:.4f} "
                    f"high=${pb.pullback_extreme:.4f} "
                    f"entry=${price:.4f} drop={drop_pct:.2f}%"
                )
                return SpikeSignal(
                    symbol=pb.symbol,
                    direction="dump",
                    price=price,
                    change_pct_1m=pb.change_pct_1m,
                    change_pct_5m=pb.change_pct_5m,
                    change_pct_15m=pb.change_pct_15m,
                    spread_pct=0.0,
                    strength=min(pb.strength + 10, 100),
                    spike_price=pb.spike_price,
                    pullback_price=pb.pullback_extreme,
                )

        return None

    def _calc_strength(
        self,
        change_1m: float,
        change_5m: float,
        change_15m: float,
        direction: str,
    ) -> int:
        """Calculate signal strength 0-100."""
        strength = 0
        sign = 1 if direction == "pump" else -1

        # 1-minute move (most important - freshest)
        abs_1m = change_1m * sign
        if abs_1m >= self._min_spike_1m:
            strength += 30
        if abs_1m >= self._min_spike_1m * 2:
            strength += 15  # Extra strong 1m

        # 5-minute move
        abs_5m = change_5m * sign
        if abs_5m >= self._min_spike_5m:
            strength += 25
        if abs_5m >= self._min_spike_5m * 1.5:
            strength += 10

        # 15-minute sustained move
        abs_15m = change_15m * sign
        if abs_15m >= self._min_spike_15m:
            strength += 15

        # Acceleration bonus: 1m move is proportionally larger than 5m
        # (move is getting faster, not slower)
        if abs_5m > 0 and abs_1m / (abs_5m / 5) > 1.5:
            strength += 5

        return min(strength, 100)

    def get_pending_pullbacks(self) -> list[dict]:
        """Get pending pullbacks for dashboard display."""
        now = time.time()
        result = []
        for symbol, pb in self._pending_pullbacks.items():
            wait_time = round(now - pb.detected_at)
            if pb.direction == "pump":
                retrace = (
                    (pb.spike_price - pb.pullback_extreme)
                    / pb.spike_price * 100
                )
            else:
                retrace = (
                    (pb.pullback_extreme - pb.spike_price)
                    / pb.spike_price * 100
                )
            result.append({
                "symbol": symbol,
                "direction": pb.direction,
                "spike_price": pb.spike_price,
                "pullback_extreme": pb.pullback_extreme,
                "retrace_pct": round(retrace, 2),
                "pullback_reached": pb.pullback_reached,
                "strength": pb.strength,
                "wait_time": wait_time,
                "max_wait": round(pb.max_wait_seconds),
                "change_1m": pb.change_pct_1m,
                "change_5m": pb.change_pct_5m,
            })
        return result

    def get_all_changes(self) -> list[dict]:
        """Get current price changes for all tracked assets (for dashboard)."""
        now = time.time()
        result = []
        for symbol, history in self._history.items():
            if not history:
                continue
            result.append({
                "symbol": symbol,
                "price": history[-1].price,
                "change_1m": round(self._calc_change(history, now, 60), 2),
                "change_5m": round(self._calc_change(history, now, 300), 2),
                "change_15m": round(self._calc_change(history, now, 900), 2),
            })
        # Sort by absolute 1m change
        result.sort(key=lambda x: abs(x["change_1m"]), reverse=True)
        return result

    def cleanup_cooldowns(self) -> None:
        """Remove expired cooldowns."""
        now = time.time()
        expired = [
            s for s, t in self._recent_signals.items()
            if now - t > self._signal_cooldown
        ]
        for s in expired:
            del self._recent_signals[s]
