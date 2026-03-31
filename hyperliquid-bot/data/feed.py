"""Real-time price and orderbook data feed."""

from __future__ import annotations

import time
from typing import Any, Optional

import pandas as pd
from loguru import logger


class DataFeed:
    """Fetches real-time price data and orderbook from Hyperliquid."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._last_prices: dict[str, float] = {}
        self._last_update: float = 0.0

    def get_current_prices(self) -> dict[str, float]:
        """Get current mid prices for all assets."""
        try:
            mids = self._client.get_all_mids()
            self._last_prices = {
                symbol: float(price) for symbol, price in mids.items()
            }
            self._last_update = time.time()
        except Exception as e:
            logger.error(f"Failed to fetch prices: {e}")
        return self._last_prices

    def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for a specific symbol."""
        if time.time() - self._last_update > 5:
            self.get_current_prices()
        return self._last_prices.get(symbol)

    def get_orderbook(self, symbol: str) -> dict:
        """Get current orderbook for a symbol."""
        try:
            book = self._client.get_orderbook(symbol)
            if not book:
                return {"bids": [], "asks": []}
            levels = book.get("levels", [[], []])
            return {
                "bids": [
                    {"price": float(l["px"]), "size": float(l["sz"])}
                    for l in levels[0]
                ] if len(levels) > 0 else [],
                "asks": [
                    {"price": float(l["px"]), "size": float(l["sz"])}
                    for l in levels[1]
                ] if len(levels) > 1 else [],
            }
        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {symbol}: {e}")
            return {"bids": [], "asks": []}

    def get_ohlcv(
        self, symbol: str, interval: str, limit: int = 500
    ) -> pd.DataFrame:
        """Get OHLCV candle data as a DataFrame."""
        try:
            candles = self._client.get_candles(symbol, interval, limit)
            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame(candles)
            df = df.rename(columns={
                "t": "timestamp",
                "T": "close_time",
                "s": "symbol",
                "i": "interval",
                "o": "open",
                "c": "close",
                "h": "high",
                "l": "low",
                "v": "volume",
                "n": "num_trades",
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
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return pd.DataFrame()

    @property
    def last_prices(self) -> dict[str, float]:
        return self._last_prices.copy()

    @property
    def last_update(self) -> float:
        return self._last_update
