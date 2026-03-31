"""Historical OHLCV data loading and management."""

from __future__ import annotations

import time
from typing import Any, Optional

import pandas as pd
from loguru import logger


class HistoricalData:
    """Loads and manages historical OHLCV data."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        limit: int = 1000,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch historical candle data."""
        try:
            if not self._client.info:
                logger.warning("No API connection - cannot fetch historical data")
                return pd.DataFrame()

            if end_time is None:
                end_time = int(time.time() * 1000)
            if start_time is None:
                interval_ms = self._client._interval_to_ms(interval)
                start_time = end_time - (limit * interval_ms)

            candles = self._client.info.candles_snapshot(
                symbol, interval, start_time, end_time
            )

            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame(candles)
            df = df.rename(columns={
                "t": "timestamp",
                "o": "open",
                "c": "close",
                "h": "high",
                "l": "low",
                "v": "volume",
            })

            for col in ["open", "close", "high", "low", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df = df.set_index("timestamp")

            df = df.sort_index()
            return df

        except Exception as e:
            logger.error(f"Failed to fetch historical data for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_extended_history(
        self,
        symbol: str,
        interval: str,
        days: int = 30,
    ) -> pd.DataFrame:
        """Fetch extended historical data by making multiple requests."""
        interval_ms = self._client._interval_to_ms(interval)
        candles_per_request = 500
        end_time = int(time.time() * 1000)
        start_time = end_time - (days * 86_400_000)

        all_frames: list[pd.DataFrame] = []
        current_start = start_time

        while current_start < end_time:
            current_end = min(
                current_start + (candles_per_request * interval_ms), end_time
            )
            df = self.fetch_candles(
                symbol, interval, candles_per_request,
                start_time=current_start, end_time=current_end
            )
            if df.empty:
                break
            all_frames.append(df)
            current_start = current_end
            time.sleep(0.2)  # Rate limiting

        if not all_frames:
            return pd.DataFrame()

        combined = pd.concat(all_frames)
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        return combined
