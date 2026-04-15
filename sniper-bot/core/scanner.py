"""Price scanner - monitors ALL Hyperliquid assets for spikes."""

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
    """Detected spike opportunity."""
    symbol: str
    direction: str  # "pump" or "dump"
    price: float
    change_pct_1m: float
    change_pct_5m: float
    change_pct_15m: float
    spread_pct: float
    strength: int  # 0-100 confidence score
    detected_at: float = field(default_factory=time.time)


class PriceScanner:
    """Scans all Hyperliquid assets for unusual price movements.

    Keeps a rolling window of prices for every asset and detects:
    - Sudden price jumps (pump) or drops (dump)
    - Acceleration (move getting faster)
    - Volume context via spread analysis
    """

    def __init__(
        self,
        min_spike_pct_1m: float = 1.5,
        min_spike_pct_5m: float = 3.0,
        min_spike_pct_15m: float = 5.0,
        history_minutes: int = 20,
        poll_interval: int = 3,
        blacklist: Optional[list[str]] = None,
    ) -> None:
        self._min_spike_1m = min_spike_pct_1m
        self._min_spike_5m = min_spike_pct_5m
        self._min_spike_15m = min_spike_pct_15m
        self._history_seconds = history_minutes * 60
        self._poll_interval = poll_interval
        self._blacklist = set(blacklist or [])

        # Price history: symbol -> deque of PriceSnapshot
        self._history: dict[str, deque[PriceSnapshot]] = {}

        # Track recently signaled symbols to avoid spam
        self._recent_signals: dict[str, float] = {}
        self._signal_cooldown = 300  # 5 min cooldown per symbol

    def update_prices(self, mids: dict[str, str]) -> list[SpikeSignal]:
        """Update all prices and detect spikes.

        Args:
            mids: Dict of symbol -> mid price string from Hyperliquid API.

        Returns:
            List of detected spike signals.
        """
        now = time.time()
        signals: list[SpikeSignal] = []

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

            # Need at least 30 seconds of data
            if len(history) < 5:
                continue

            # Calculate price changes over different windows
            change_1m = self._calc_change(history, now, 60)
            change_5m = self._calc_change(history, now, 300)
            change_15m = self._calc_change(history, now, 900)

            # Detect spike
            spike = self._detect_spike(
                symbol, price, change_1m, change_5m, change_15m, now
            )
            if spike:
                signals.append(spike)

        return signals

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
    ) -> Optional[SpikeSignal]:
        """Check if price changes qualify as a snipeable spike."""

        # Check cooldown
        last_signal = self._recent_signals.get(symbol, 0)
        if now - last_signal < self._signal_cooldown:
            return None

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
            return None

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
            return None

        # Calculate strength (0-100)
        strength = self._calc_strength(
            change_1m, change_5m, change_15m, direction
        )

        # Mark as signaled
        self._recent_signals[symbol] = now

        signal = SpikeSignal(
            symbol=symbol,
            direction=direction,
            price=price,
            change_pct_1m=round(change_1m, 2),
            change_pct_5m=round(change_5m, 2),
            change_pct_15m=round(change_15m, 2),
            spread_pct=0.0,
            strength=strength,
        )

        logger.info(
            f"SPIKE DETECTED: {symbol} {direction.upper()} "
            f"1m={change_1m:+.2f}% 5m={change_5m:+.2f}% "
            f"15m={change_15m:+.2f}% strength={strength}%"
        )

        return signal

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
