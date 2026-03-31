"""In-memory cache for recent market data."""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd
from loguru import logger


class DataCache:
    """Caches recent OHLCV data to reduce API calls."""

    def __init__(self, ttl_seconds: int = 30) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, dict] = {}

    def _cache_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}"

    def get(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """Get cached data if still valid."""
        key = self._cache_key(symbol, interval)
        entry = self._cache.get(key)
        if entry is None:
            return None

        if time.time() - entry["timestamp"] > self._ttl:
            del self._cache[key]
            return None

        return entry["data"]

    def set(self, symbol: str, interval: str, data: pd.DataFrame) -> None:
        """Store data in cache."""
        key = self._cache_key(symbol, interval)
        self._cache[key] = {
            "data": data,
            "timestamp": time.time(),
        }

    def invalidate(self, symbol: Optional[str] = None) -> None:
        """Invalidate cache entries."""
        if symbol is None:
            self._cache.clear()
        else:
            keys_to_remove = [
                k for k in self._cache if k.startswith(f"{symbol}_")
            ]
            for key in keys_to_remove:
                del self._cache[key]

    def get_or_fetch(
        self, symbol: str, interval: str, fetch_fn: callable
    ) -> pd.DataFrame:
        """Get from cache or fetch and cache."""
        cached = self.get(symbol, interval)
        if cached is not None:
            return cached

        data = fetch_fn(symbol, interval)
        if not data.empty:
            self.set(symbol, interval, data)
        return data

    @property
    def size(self) -> int:
        return len(self._cache)
