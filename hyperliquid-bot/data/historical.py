"""
Chargement des données OHLCV historiques depuis Hyperliquid.

Récupère les bougies historiques par plages de temps, gère
la pagination et retourne des DataFrames pandas normalisés.
"""

import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from core.client import HyperliquidClient
from data.cache import DataCache

# Colonnes standardisées du DataFrame OHLCV
OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Mapping interval -> millisecondes
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

# Nombre max de bougies par requête Hyperliquid
MAX_CANDLES_PER_REQUEST = 5000


class HistoricalData:
    """
    Fournisseur de données OHLCV historiques.

    Récupère et normalise les données depuis l'API Hyperliquid
    avec support du cache et de la pagination automatique.
    """

    def __init__(self, client: HyperliquidClient, cache: DataCache) -> None:
        """
        Initialise le fournisseur de données historiques.

        Args:
            client: Client Hyperliquid authentifié.
            cache: Cache en mémoire.
        """
        self.client = client
        self.cache = cache

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        use_cache: bool = True,
    ) -> Optional[pd.DataFrame]:
        """
        Récupère les données OHLCV récentes pour un symbole.

        Args:
            symbol: Symbole de l'actif (ex: "BTC").
            interval: Intervalle ("1m", "5m", "15m", "1h", "4h", "1d").
            limit: Nombre de bougies à récupérer.
            use_cache: Utilise le cache si disponible.

        Returns:
            DataFrame OHLCV ou None si erreur.
        """
        if use_cache:
            cached = self.cache.get_candles(symbol, interval)
            if cached is not None and len(cached) >= limit:
                return cached.tail(limit).reset_index(drop=True)

        interval_ms = INTERVAL_MS.get(interval)
        if not interval_ms:
            logger.error(f"Intervalle non supporté: {interval}")
            return None

        end_time = int(time.time() * 1000)
        start_time = end_time - (interval_ms * limit)

        df = self._fetch_candles(symbol, interval, start_time, end_time)
        if df is not None and not df.empty:
            self.cache.set_candles(symbol, interval, df)

        return df

    def get_ohlcv_range(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Récupère les données OHLCV sur une plage de dates.

        Args:
            symbol: Symbole de l'actif.
            interval: Intervalle de temps.
            start_date: Date de début.
            end_date: Date de fin (défaut: maintenant).

        Returns:
            DataFrame OHLCV ou None si erreur.
        """
        if end_date is None:
            end_date = datetime.utcnow()

        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)

        interval_ms = INTERVAL_MS.get(interval, 3_600_000)
        chunks = []
        current_start = start_ms

        while current_start < end_ms:
            chunk_end = min(
                current_start + interval_ms * MAX_CANDLES_PER_REQUEST,
                end_ms,
            )
            df_chunk = self._fetch_candles(symbol, interval, current_start, chunk_end)
            if df_chunk is not None and not df_chunk.empty:
                chunks.append(df_chunk)
            current_start = chunk_end + 1

        if not chunks:
            return None

        df = pd.concat(chunks, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        return df.reset_index(drop=True)

    def _fetch_candles(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> Optional[pd.DataFrame]:
        """
        Appelle l'API et normalise les données en DataFrame.

        Args:
            symbol: Symbole de l'actif.
            interval: Intervalle de temps.
            start_ms: Timestamp de début en ms.
            end_ms: Timestamp de fin en ms.

        Returns:
            DataFrame OHLCV normalisé ou None si erreur.
        """
        raw = self.client.get_candles(symbol, interval, start_ms, end_ms)
        if not raw:
            logger.warning(f"Aucune donnée historique pour {symbol} {interval}")
            return None

        try:
            rows = []
            for candle in raw:
                rows.append({
                    "timestamp": pd.Timestamp(candle["t"], unit="ms", tz="UTC"),
                    "open": float(candle["o"]),
                    "high": float(candle["h"]),
                    "low": float(candle["l"]),
                    "close": float(candle["c"]),
                    "volume": float(candle["v"]),
                })

            df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
            df = df.sort_values("timestamp").reset_index(drop=True)
            logger.debug(
                f"Données chargées: {symbol} {interval} — {len(df)} bougies"
            )
            return df

        except (KeyError, ValueError, TypeError) as exc:
            logger.error(f"Erreur normalisation données {symbol} {interval}: {exc}")
            return None

    def get_multi_symbol_ohlcv(
        self,
        symbols: list[str],
        interval: str,
        limit: int = 500,
    ) -> dict[str, pd.DataFrame]:
        """
        Récupère les données OHLCV pour plusieurs symboles.

        Args:
            symbols: Liste de symboles.
            interval: Intervalle de temps.
            limit: Nombre de bougies par symbole.

        Returns:
            Dictionnaire {symbol: DataFrame}.
        """
        result = {}
        for symbol in symbols:
            df = self.get_ohlcv(symbol, interval, limit)
            if df is not None:
                result[symbol] = df
            else:
                logger.warning(f"Données manquantes pour {symbol} {interval}")
        return result
