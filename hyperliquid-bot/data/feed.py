"""
Flux de données en temps réel — prix, orderbook et mises à jour de marché.

Gère la récupération périodique des données live depuis Hyperliquid
et distribue les mises à jour aux composants abonnés.
"""

import asyncio
from typing import Callable, Optional

from loguru import logger

from core.client import HyperliquidClient
from data.cache import DataCache
from data.historical import HistoricalData


class DataFeed:
    """
    Flux de données de marché en temps réel.

    Agrège les prix mid, les orderboks et les données OHLCV
    et notifie les abonnés lors de chaque mise à jour.
    """

    def __init__(
        self,
        client: HyperliquidClient,
        cache: DataCache,
        historical: HistoricalData,
    ) -> None:
        """
        Initialise le flux de données.

        Args:
            client: Client Hyperliquid authentifié.
            cache: Cache en mémoire.
            historical: Fournisseur de données historiques.
        """
        self.client = client
        self.cache = cache
        self.historical = historical

        self._price_callbacks: list[Callable[[dict[str, float]], None]] = []
        self._running = False
        self._current_prices: dict[str, float] = {}
        logger.info("DataFeed initialisé.")

    def subscribe_prices(self, callback: Callable[[dict[str, float]], None]) -> None:
        """
        Abonne un callback aux mises à jour de prix.

        Args:
            callback: Fonction appelée avec {symbol: price} à chaque mise à jour.
        """
        self._price_callbacks.append(callback)

    async def start(self, update_interval: float = 5.0) -> None:
        """
        Démarre le flux de données en boucle.

        Args:
            update_interval: Intervalle de mise à jour en secondes.
        """
        self._running = True
        logger.info(f"DataFeed démarré — intervalle: {update_interval}s")

        while self._running:
            try:
                await self._update_prices()
                await asyncio.sleep(update_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Erreur DataFeed: {exc}")
                await asyncio.sleep(update_interval)

    def stop(self) -> None:
        """Arrête le flux de données."""
        self._running = False
        logger.info("DataFeed arrêté.")

    async def _update_prices(self) -> None:
        """Récupère et distribue les prix mid de tous les actifs."""
        loop = asyncio.get_event_loop()
        mids = await loop.run_in_executor(None, self.client.get_all_mids)

        if not mids:
            logger.warning("Impossible de récupérer les prix mid.")
            return

        prices: dict[str, float] = {}
        for symbol, price_str in mids.items():
            try:
                prices[symbol] = float(price_str)
            except (ValueError, TypeError):
                continue

        self._current_prices = prices
        self.cache.set_prices_bulk(prices)

        for callback in self._price_callbacks:
            try:
                callback(prices)
            except Exception as exc:
                logger.error(f"Erreur callback prix: {exc}")

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Retourne le dernier prix connu pour un symbole.

        Args:
            symbol: Symbole de l'actif.

        Returns:
            Prix ou None si inconnu.
        """
        cached = self.cache.get_price(symbol)
        if cached is not None:
            return cached
        return self._current_prices.get(symbol)

    def get_all_prices(self) -> dict[str, float]:
        """Retourne tous les prix actuels."""
        return self._current_prices.copy()

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        force_refresh: bool = False,
    ) -> Optional[object]:
        """
        Retourne les données OHLCV (depuis cache ou API).

        Args:
            symbol: Symbole de l'actif.
            interval: Intervalle de temps.
            limit: Nombre de bougies.
            force_refresh: Force le rechargement depuis l'API.

        Returns:
            DataFrame OHLCV ou None.
        """
        if force_refresh:
            self.cache.invalidate_candles(symbol)
        return self.historical.get_ohlcv(symbol, interval, limit)

    def get_orderbook(self, symbol: str) -> Optional[dict]:
        """
        Retourne l'orderbook d'un symbole.

        Args:
            symbol: Symbole de l'actif.

        Returns:
            Orderbook {bids: [...], asks: [...]} ou None.
        """
        cached = self.cache.get_orderbook(symbol)
        if cached is not None:
            return cached

        book = self.client.get_l2_book(symbol)
        if book:
            self.cache.set_orderbook(symbol, book)
        return book

    def get_mid_spread(self, symbol: str) -> Optional[tuple[float, float, float]]:
        """
        Calcule le spread bid/ask depuis l'orderbook.

        Args:
            symbol: Symbole de l'actif.

        Returns:
            Tuple (bid, ask, spread_pct) ou None.
        """
        book = self.get_orderbook(symbol)
        if not book:
            return None

        try:
            levels = book.get("levels", [[], []])
            bids = levels[0]
            asks = levels[1]

            if not bids or not asks:
                return None

            best_bid = float(bids[0]["px"])
            best_ask = float(asks[0]["px"])
            spread_pct = ((best_ask - best_bid) / best_bid) * 100

            return best_bid, best_ask, spread_pct
        except (IndexError, KeyError, ValueError, TypeError):
            return None
