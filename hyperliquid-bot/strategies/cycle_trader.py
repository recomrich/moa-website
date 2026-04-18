"""Cycle Trader strategy - detects and exploits recurring price oscillation cycles.

Cryptos like BTC, ETH, SOL oscillate in multi-day cycles: +5% over 2 days,
-3% over 1.5 days, +4% over 2.5 days, etc. This strategy:

1. ANALYZES 30-60 days of daily OHLC to identify up/down cycles
2. DETECTS each cycle's duration (days) and amplitude (% move)
3. PREDICTS where we are in the current cycle and when the reversal is expected
4. BUYS at the predicted bottom of a down-cycle (with leverage)
5. SELLS/SHORTS at the predicted top of an up-cycle (with leverage)

Cycle metrics computed per asset:
  - avg_up_duration / avg_down_duration (days)
  - avg_up_amplitude / avg_down_amplitude (%)
  - cycle_reliability (0-100%)
  - current_cycle_day, current_direction, expected_reversal_in
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd
from loguru import logger

from indicators.momentum import rsi
from indicators.volatility import atr
from strategies.base_strategy import BaseStrategy, Signal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CycleSegment:
    """One contiguous up-move or down-move."""

    direction: str          # "up" or "down"
    start_price: float
    end_price: float
    duration_days: float    # number of calendar days (can be fractional)
    amplitude_pct: float    # signed percent change (positive for up, negative for down)


@dataclass
class CycleAnalysis:
    """Aggregated statistics about the recurring cycles for one asset."""

    avg_up_duration: float       # average days an up-move lasts
    avg_down_duration: float     # average days a down-move lasts
    avg_up_amplitude: float      # average % gain during up-moves (positive)
    avg_down_amplitude: float    # average % loss during down-moves (negative)
    cycle_reliability: float     # 0-100, consistency score
    current_cycle_day: float     # days into the current move
    current_direction: str       # "up" or "down"
    expected_reversal_in: float  # estimated days/hours until next reversal
    segments: List[CycleSegment]


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class CycleTraderStrategy(BaseStrategy):
    """Cycle trading: predict oscillation reversals and trade them with leverage.

    BUY signal:
        We are near the end of a down-cycle:
          current_cycle_day >= avg_down_duration * 0.8
          AND the cumulative drop is approaching avg_down_amplitude
          AND RSI is low (oversold territory)

    SELL signal:
        We are near the end of an up-cycle:
          current_cycle_day >= avg_up_duration * 0.8
          AND the cumulative rise is approaching avg_up_amplitude
          AND RSI is high (overbought territory)
    """

    def __init__(self, params: dict | None = None) -> None:
        params = params or {}
        timeframe = params.get("timeframe", "15m")
        super().__init__("cycle_trader", timeframe, params)

        # How many days of daily data to analyze for cycle detection
        self._lookback_days: int = params.get("lookback_days", 45)
        # Minimum number of complete cycles needed for reliable statistics
        self._min_cycles: int = params.get("min_cycles", 4)
        # Minimum cycle reliability score (0-100) to act on
        self._min_reliability: float = params.get("min_reliability", 40.0)
        # Threshold multiplier: signal fires when current_cycle_day >= avg_duration * threshold
        self._duration_threshold: float = params.get("duration_threshold", 0.8)
        # Amplitude proximity: signal fires when current move is within this fraction of avg amplitude
        self._amplitude_proximity: float = params.get("amplitude_proximity", 0.65)
        # RSI thresholds
        self._rsi_buy_max: float = params.get("rsi_buy_max", 45)
        self._rsi_sell_min: float = params.get("rsi_sell_min", 55)
        # RSI period
        self._rsi_period: int = params.get("rsi_period", 14)
        # ATR period
        self._atr_period: int = params.get("atr_period", 14)
        # Smoothing: minimum % move to count as a real directional swing (filters noise)
        self._min_swing_pct: float = params.get("min_swing_pct", 1.0)

    # ------------------------------------------------------------------
    # Main signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Analyze cycles in historical data and generate a trading signal."""
        if len(df) < 15:
            logger.debug(f"[{self.name}] Not enough daily bars ({len(df)})")
            return Signal.HOLD

        # With timeframe "1d", df is already daily data - use directly
        if self.timeframe == "1d":
            daily = df.copy()
            if "close" not in daily.columns:
                return Signal.HOLD
        else:
            daily = self._build_daily(df)
            if daily is None or len(daily) < 10:
                logger.debug(f"[{self.name}] Not enough daily bars")
                return Signal.HOLD

        # Run cycle analysis on the daily data
        analysis = self._analyze_cycles(daily)
        if analysis is None:
            return Signal.HOLD

        # Current price and indicators
        current_close = float(df["close"].iloc[-1])
        rsi_vals = rsi(df, period=self._rsi_period)
        current_rsi = float(rsi_vals.iloc[-1]) if rsi_vals is not None and not rsi_vals.empty else 50.0
        if pd.isna(current_rsi):
            current_rsi = 50.0

        atr_vals = atr(df, period=self._atr_period)
        current_atr = float(atr_vals.iloc[-1]) if atr_vals is not None and not atr_vals.empty else 0.0
        if pd.isna(current_atr):
            current_atr = 0.0

        # Log the full cycle analysis
        self._log_analysis(analysis, current_close, current_rsi, current_atr)

        # --- Decision logic ---

        # Check minimum reliability
        if analysis.cycle_reliability < self._min_reliability:
            logger.info(
                f"[{self.name}] Cycle reliability too low "
                f"({analysis.cycle_reliability:.1f}% < {self._min_reliability}%), holding"
            )
            return Signal.HOLD

        # Compute how far through the current cycle we are (0.0 to 1.0+)
        if analysis.current_direction == "down":
            if analysis.avg_down_duration <= 0:
                return Signal.HOLD
            cycle_progress = analysis.current_cycle_day / analysis.avg_down_duration
            # How much has the price dropped relative to the average down-amplitude?
            current_move_pct = self._current_move_amplitude(daily)
            amplitude_progress = abs(current_move_pct) / abs(analysis.avg_down_amplitude) if analysis.avg_down_amplitude != 0 else 0

            if (cycle_progress >= self._duration_threshold
                    and amplitude_progress >= self._amplitude_proximity
                    and current_rsi <= self._rsi_buy_max):
                self._signal_count += 1
                logger.info(
                    f"[{self.name}] >>> BUY SIGNAL <<< "
                    f"Down-cycle near completion: "
                    f"day {analysis.current_cycle_day:.1f}/{analysis.avg_down_duration:.1f} "
                    f"({cycle_progress:.0%} through), "
                    f"drop {current_move_pct:+.2f}% vs avg {analysis.avg_down_amplitude:+.2f}% "
                    f"({amplitude_progress:.0%} of avg amplitude), "
                    f"RSI={current_rsi:.1f}, "
                    f"reversal expected in ~{analysis.expected_reversal_in:.1f} days"
                )
                return Signal.BUY

        elif analysis.current_direction == "up":
            if analysis.avg_up_duration <= 0:
                return Signal.HOLD
            cycle_progress = analysis.current_cycle_day / analysis.avg_up_duration
            current_move_pct = self._current_move_amplitude(daily)
            amplitude_progress = abs(current_move_pct) / abs(analysis.avg_up_amplitude) if analysis.avg_up_amplitude != 0 else 0

            if (cycle_progress >= self._duration_threshold
                    and amplitude_progress >= self._amplitude_proximity
                    and current_rsi >= self._rsi_sell_min):
                self._signal_count += 1
                logger.info(
                    f"[{self.name}] >>> SELL SIGNAL <<< "
                    f"Up-cycle near completion: "
                    f"day {analysis.current_cycle_day:.1f}/{analysis.avg_up_duration:.1f} "
                    f"({cycle_progress:.0%} through), "
                    f"rise {current_move_pct:+.2f}% vs avg {analysis.avg_up_amplitude:+.2f}% "
                    f"({amplitude_progress:.0%} of avg amplitude), "
                    f"RSI={current_rsi:.1f}, "
                    f"reversal expected in ~{analysis.expected_reversal_in:.1f} days"
                )
                return Signal.SELL

        return Signal.HOLD

    # ------------------------------------------------------------------
    # Cycle analysis engine
    # ------------------------------------------------------------------

    def _analyze_cycles(self, daily: pd.DataFrame) -> CycleAnalysis | None:
        """Segment daily data into up/down cycles and compute statistics.

        A cycle boundary is detected when the cumulative move from the last
        turning point reverses by more than ``_min_swing_pct`` percent.
        """
        lookback = daily.iloc[-self._lookback_days:] if len(daily) > self._lookback_days else daily
        closes = lookback["close"].astype(float).values
        if len(closes) < 5:
            return None

        # ---- Identify turning points using a minimum swing filter ----
        segments: List[CycleSegment] = []

        # Starting state
        anchor_idx = 0
        anchor_price = closes[0]
        extreme_idx = 0
        extreme_price = closes[0]
        direction: str | None = None  # not yet determined

        for i in range(1, len(closes)):
            price = closes[i]

            if direction is None:
                # Determine initial direction from first significant move
                move_pct = ((price - anchor_price) / anchor_price) * 100
                if move_pct >= self._min_swing_pct:
                    direction = "up"
                    extreme_idx = i
                    extreme_price = price
                elif move_pct <= -self._min_swing_pct:
                    direction = "down"
                    extreme_idx = i
                    extreme_price = price
                continue

            if direction == "up":
                if price > extreme_price:
                    extreme_price = price
                    extreme_idx = i
                else:
                    # Check if we have reversed enough from the extreme
                    reversal_pct = ((price - extreme_price) / extreme_price) * 100
                    if reversal_pct <= -self._min_swing_pct:
                        # Record the completed up-segment (anchor -> extreme)
                        seg_amplitude = ((extreme_price - anchor_price) / anchor_price) * 100
                        seg_duration = max(extreme_idx - anchor_idx, 1)
                        segments.append(CycleSegment(
                            direction="up",
                            start_price=anchor_price,
                            end_price=extreme_price,
                            duration_days=float(seg_duration),
                            amplitude_pct=seg_amplitude,
                        ))
                        # New segment starts from the extreme
                        anchor_idx = extreme_idx
                        anchor_price = extreme_price
                        extreme_idx = i
                        extreme_price = price
                        direction = "down"

            elif direction == "down":
                if price < extreme_price:
                    extreme_price = price
                    extreme_idx = i
                else:
                    reversal_pct = ((price - extreme_price) / extreme_price) * 100
                    if reversal_pct >= self._min_swing_pct:
                        # Record the completed down-segment (anchor -> extreme)
                        seg_amplitude = ((extreme_price - anchor_price) / anchor_price) * 100
                        seg_duration = max(extreme_idx - anchor_idx, 1)
                        segments.append(CycleSegment(
                            direction="down",
                            start_price=anchor_price,
                            end_price=extreme_price,
                            duration_days=float(seg_duration),
                            amplitude_pct=seg_amplitude,
                        ))
                        anchor_idx = extreme_idx
                        anchor_price = extreme_price
                        extreme_idx = i
                        extreme_price = price
                        direction = "up"

        # The current (incomplete) segment: from last anchor to now
        current_direction = direction or "up"
        current_cycle_day = float(len(closes) - 1 - anchor_idx)

        # Need enough completed segments for statistics
        up_segments = [s for s in segments if s.direction == "up"]
        down_segments = [s for s in segments if s.direction == "down"]

        total_completed = len(up_segments) + len(down_segments)
        if total_completed < self._min_cycles:
            logger.debug(
                f"[{self.name}] Only {total_completed} completed cycles "
                f"(need {self._min_cycles}), skipping"
            )
            return None

        # ---- Compute averages ----
        avg_up_duration = float(np.mean([s.duration_days for s in up_segments])) if up_segments else 0.0
        avg_down_duration = float(np.mean([s.duration_days for s in down_segments])) if down_segments else 0.0
        avg_up_amplitude = float(np.mean([s.amplitude_pct for s in up_segments])) if up_segments else 0.0
        avg_down_amplitude = float(np.mean([s.amplitude_pct for s in down_segments])) if down_segments else 0.0

        # ---- Cycle reliability ----
        # Measures how consistent the durations and amplitudes are across cycles.
        # Lower coefficient of variation = more predictable = higher reliability.
        reliability = self._compute_reliability(up_segments, down_segments)

        # ---- Expected reversal ----
        if current_direction == "up":
            expected_remaining = max(avg_up_duration - current_cycle_day, 0.0)
        else:
            expected_remaining = max(avg_down_duration - current_cycle_day, 0.0)

        return CycleAnalysis(
            avg_up_duration=avg_up_duration,
            avg_down_duration=avg_down_duration,
            avg_up_amplitude=avg_up_amplitude,
            avg_down_amplitude=avg_down_amplitude,
            cycle_reliability=reliability,
            current_cycle_day=current_cycle_day,
            current_direction=current_direction,
            expected_reversal_in=expected_remaining,
            segments=segments,
        )

    def _compute_reliability(
        self,
        up_segments: List[CycleSegment],
        down_segments: List[CycleSegment],
    ) -> float:
        """Compute a 0-100 reliability score based on cycle consistency.

        Uses the coefficient of variation (CV = std/mean) of both durations
        and amplitudes.  A CV of 0 means perfectly consistent (score 100).
        A CV >= 1.0 means very inconsistent (score 0).
        """
        cv_values: list[float] = []

        for segs, label in [(up_segments, "up"), (down_segments, "down")]:
            if len(segs) < 2:
                continue
            durations = np.array([s.duration_days for s in segs])
            amplitudes = np.array([abs(s.amplitude_pct) for s in segs])

            for arr in [durations, amplitudes]:
                mean = np.mean(arr)
                if mean > 0:
                    cv = float(np.std(arr) / mean)
                    cv_values.append(cv)

        if not cv_values:
            return 0.0

        avg_cv = float(np.mean(cv_values))
        # Map CV to a 0-100 score. CV=0 -> 100, CV>=1 -> 0
        score = max(0.0, min(100.0, (1.0 - avg_cv) * 100.0))
        return round(score, 1)

    def _current_move_amplitude(self, daily: pd.DataFrame) -> float:
        """Calculate the % move from the start of the current (incomplete) cycle segment.

        Uses the same turning-point detection as _analyze_cycles to find the
        last anchor point, then measures from there to the current close.
        """
        closes = daily["close"].astype(float).values
        if len(closes) < 2:
            return 0.0

        # Walk backwards to find the last turning point using the swing filter
        anchor_price = closes[-1]
        # Re-run a simplified version: find the last significant reversal
        # by scanning from the end backwards
        extreme_price = closes[-1]
        anchor_idx = len(closes) - 1

        for i in range(len(closes) - 2, -1, -1):
            price = closes[i]
            move_from_current = ((closes[-1] - price) / price) * 100

            # If the direction from this point to now changed sign compared to
            # the direction from the next point to now, we found a turning point.
            if i < len(closes) - 2:
                prev_move = ((closes[-1] - closes[i + 1]) / closes[i + 1]) * 100
                curr_move = ((closes[-1] - price) / price) * 100
                # Check if we crossed zero or the move started diminishing
                # Simpler: just find where the direction inverts
                segment_move = ((closes[i + 1] - price) / price) * 100
                if abs(segment_move) >= self._min_swing_pct:
                    if (segment_move > 0 and curr_move < prev_move) or \
                       (segment_move < 0 and curr_move > prev_move):
                        # Price at i+1 was a turning point relative to end
                        pass

        # Simpler approach: use the segments from _analyze_cycles
        # The last anchor is at the start of the current incomplete segment
        # We detect it as: walk from beginning using the swing filter, and
        # the last completed segment's end_price is the anchor.
        # For efficiency, just compute from the last local extreme.

        # Find the last local min or max that is at least _min_swing_pct away
        # from some subsequent extreme.
        last_anchor = closes[0]
        direction = None
        extreme = closes[0]

        for i in range(1, len(closes)):
            p = closes[i]
            if direction is None:
                mv = ((p - last_anchor) / last_anchor) * 100
                if mv >= self._min_swing_pct:
                    direction = "up"
                    extreme = p
                elif mv <= -self._min_swing_pct:
                    direction = "down"
                    extreme = p
                continue

            if direction == "up":
                if p > extreme:
                    extreme = p
                else:
                    rev = ((p - extreme) / extreme) * 100
                    if rev <= -self._min_swing_pct:
                        last_anchor = extreme
                        extreme = p
                        direction = "down"
            else:
                if p < extreme:
                    extreme = p
                else:
                    rev = ((p - extreme) / extreme) * 100
                    if rev >= self._min_swing_pct:
                        last_anchor = extreme
                        extreme = p
                        direction = "up"

        current_close = closes[-1]
        if last_anchor <= 0:
            return 0.0
        return ((current_close - last_anchor) / last_anchor) * 100

    # ------------------------------------------------------------------
    # Daily OHLC builder
    # ------------------------------------------------------------------

    def _build_daily(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Build daily OHLC from intraday data."""
        try:
            data = df.copy()

            if "timestamp" in data.columns:
                data["date"] = pd.to_datetime(data["timestamp"], unit="ms").dt.date
            elif hasattr(data.index, "date"):
                data["date"] = data.index.date
            else:
                # Estimate bars per day from timeframe
                bars_per_day = {
                    "1m": 1440, "5m": 288, "15m": 96,
                    "30m": 48, "1h": 24, "4h": 6,
                }.get(self.timeframe, 96)
                if len(data) < bars_per_day * 3:
                    return None
                data["date"] = [i // bars_per_day for i in range(len(data))]

            daily = data.groupby("date").agg(
                high=("high", "max"),
                low=("low", "min"),
                open=("open", "first"),
                close=("close", "last"),
            )
            return daily if len(daily) >= 5 else None

        except Exception as e:
            logger.debug(f"[{self.name}] Daily OHLC build error: {e}")
            return None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_analysis(
        self,
        analysis: CycleAnalysis,
        current_close: float,
        current_rsi: float,
        current_atr: float,
    ) -> None:
        """Log detailed cycle analysis info."""
        up_count = sum(1 for s in analysis.segments if s.direction == "up")
        down_count = sum(1 for s in analysis.segments if s.direction == "down")

        logger.info(
            f"[{self.name}] === Cycle Analysis ===\n"
            f"  Completed cycles: {up_count} up, {down_count} down\n"
            f"  Avg UP   move: {analysis.avg_up_amplitude:+.2f}% over {analysis.avg_up_duration:.1f} days\n"
            f"  Avg DOWN move: {analysis.avg_down_amplitude:+.2f}% over {analysis.avg_down_duration:.1f} days\n"
            f"  Cycle reliability: {analysis.cycle_reliability:.1f}%\n"
            f"  Current state: {analysis.current_direction.upper()} for "
            f"{analysis.current_cycle_day:.1f} days\n"
            f"  Expected reversal in: ~{analysis.expected_reversal_in:.1f} days\n"
            f"  Price=${current_close:.4f}, RSI={current_rsi:.1f}, ATR=${current_atr:.4f}"
        )

    # ------------------------------------------------------------------
    # Stop-loss and take-profit (ATR-based)
    # ------------------------------------------------------------------

    def get_stop_loss(
        self, entry_price: float, atr_value: float, side: str = "buy"
    ) -> float:
        """SL at 1.2x ATR from entry."""
        mult = 1.2
        if side == "buy":
            return round(entry_price - (atr_value * mult), 6)
        return round(entry_price + (atr_value * mult), 6)

    def get_take_profit(
        self, entry_price: float, atr_value: float,
        side: str = "buy", ratio: float = 2.0
    ) -> float:
        """TP at 2x ATR from entry (R:R ~ 1.67 with 1.2x ATR SL)."""
        mult = 2.0
        if side == "buy":
            return round(entry_price + (atr_value * mult), 6)
        return round(entry_price - (atr_value * mult), 6)
