"""
Cache en mémoire pour les données de marché récentes.

Évite les appels API répétés pour des données identiques
en maintenant un cache TTL par symbole et timeframe.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
from loguru import logger


@dataclass
class CacheEntry:
    """Entrée du cache avec TTL."""
    data: Any
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 60.0

    @property
    def is_expired(self) -> bool:
        """Vérifie si l'entrée est expirée."""
        return (time.time() - self.created_at) > self.ttl_seconds


class DataCache:
    """
    Cache en mémoire avec TTL pour les données de marché.

    Stocke les DataFrames OHLCV, les prix mid et les orderboks
    avec des TTLs configurables par type de donnée.
    """

    # TTLs par type de données (secondes)
    TTL_CANDLES = {
        "1m": 30,
        "5m": 60,
        "15m": 120,
        "1h": 300,
        "4h": 600,
        "1d": 3600,
    }
    TTL_MID_PRICE = 5
    TTL_ORDERBOOK = 3

    def __init__(self) -> None:
        """Initialise le cache."""
        self._candles: dict[str, CacheEntry] = {}
        self._prices: dict[str, CacheEntry] = {}
        self._orderbooks: dict[str, CacheEntry] = {}
        logger.debug("DataCache initialisé.")

    def set_candles(
        self, symbol: str, interval: str, df: pd.DataFrame
    ) -> None:
        """
        Met en cache un DataFrame de bougies OHLCV.

        Args:
            symbol: Symbole de l'actif.
            interval: Intervalle de temps.
            df: DataFrame OHLCV.
        """
        key = f"{symbol}_{interval}"
        ttl = self.TTL_CANDLES.get(interval, 60)
        self._candles[key] = CacheEntry(data=df.copy(), ttl_seconds=ttl)

    def get_candles(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """
        Récupère les bougies depuis le cache.

        Args:
            symbol: Symbole de l'actif.
            interval: Intervalle de temps.

        Returns:
            DataFrame OHLCV ou None si absent ou expiré.
        """
        key = f"{symbol}_{interval}"
        entry = self._candles.get(key)
        if entry is None or entry.is_expired:
            return None
        return entry.data.copy()

    def set_price(self, symbol: str, price: float) -> None:
        """
        Met en cache le prix mid d'un actif.

        Args:
            symbol: Symbole de l'actif.
            price: Prix mid.
        """
        self._prices[symbol] = CacheEntry(
            data=price, ttl_seconds=self.TTL_MID_PRICE
        )

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Récupère le prix mid depuis le cache.

        Args:
            symbol: Symbole de l'actif.

        Returns:
            Prix mid ou None si absent ou expiré.
        """
        entry = self._prices.get(symbol)
        if entry is None or entry.is_expired:
            return None
        return entry.data

    def set_prices_bulk(self, prices: dict[str, float]) -> None:
        """
        Met en cache les prix de plusieurs actifs.

        Args:
            prices: Dictionnaire {symbol: price}.
        """
        for symbol, price in prices.items():
            self.set_price(symbol, price)

    def get_all_prices(self) -> dict[str, float]:
        """
        Retourne tous les prix en cache non expirés.

        Returns:
            Dictionnaire {symbol: price}.
        """
        return {
            symbol: entry.data
            for symbol, entry in self._prices.items()
            if not entry.is_expired
        }

    def set_orderbook(self, symbol: str, orderbook: dict) -> None:
        """
        Met en cache l'orderbook d'un actif.

        Args:
            symbol: Symbole de l'actif.
            orderbook: Données de l'orderbook.
        """
        self._orderbooks[symbol] = CacheEntry(
            data=orderbook, ttl_seconds=self.TTL_ORDERBOOK
        )

    def get_orderbook(self, symbol: str) -> Optional[dict]:
        """
        Récupère l'orderbook depuis le cache.

        Args:
            symbol: Symbole de l'actif.

        Returns:
            Orderbook ou None si absent ou expiré.
        """
        entry = self._orderbooks.get(symbol)
        if entry is None or entry.is_expired:
            return None
        return entry.data

    def invalidate_candles(self, symbol: Optional[str] = None) -> None:
        """
        Invalide le cache des bougies.

        Args:
            symbol: Si fourni, invalide uniquement ce symbole.
        """
        if symbol is None:
            self._candles.clear()
        else:
            keys_to_delete = [k for k in self._candles if k.startswith(f"{symbol}_")]
            for key in keys_to_delete:
                del self._candles[key]

    def cleanup_expired(self) -> int:
        """
        Supprime les entrées expirées de tous les caches.

        Returns:
            Nombre d'entrées supprimées.
        """
        count = 0
        for cache in [self._candles, self._prices, self._orderbooks]:
            expired_keys = [k for k, v in cache.items() if v.is_expired]
            for key in expired_keys:
                del cache[key]
                count += 1
        return count

    def get_stats(self) -> dict:
        """Retourne les statistiques du cache."""
        return {
            "candles_entries": len(self._candles),
            "price_entries": len(self._prices),
            "orderbook_entries": len(self._orderbooks),
        }
