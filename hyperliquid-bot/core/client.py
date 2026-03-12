"""
Hyperliquid client — connexion et authentification.

Gère la connexion à l'API Hyperliquid (mainnet ou testnet) et fournit
un accès unifié aux fonctions de trading spot et perps.
"""

import asyncio
import time
from typing import Any, Optional

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from loguru import logger


class HyperliquidClient:
    """Client principal pour interagir avec l'API Hyperliquid."""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0  # secondes

    def __init__(self, private_key: str, wallet_address: str, network: str = "mainnet") -> None:
        """
        Initialise le client Hyperliquid.

        Args:
            private_key: Clé privée du wallet (sans préfixe 0x).
            wallet_address: Adresse publique du wallet.
            network: "mainnet" ou "testnet".
        """
        self._private_key = private_key
        self.wallet_address = wallet_address
        self.network = network

        base_url = (
            constants.MAINNET_API_URL
            if network == "mainnet"
            else constants.TESTNET_API_URL
        )

        self._account = Account.from_key(private_key)
        self.info = Info(base_url, skip_ws=True)
        self.exchange = Exchange(self._account, base_url, account_address=wallet_address)

        self._connected = False
        logger.info(f"Client Hyperliquid initialisé — réseau: {network}")

    async def connect(self) -> bool:
        """
        Vérifie la connexion en récupérant les informations du compte.

        Returns:
            True si la connexion est établie, False sinon.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                state = self.info.user_state(self.wallet_address)
                if state:
                    self._connected = True
                    logger.info(
                        f"Connexion Hyperliquid réussie — "
                        f"solde: ${self._extract_balance(state):.2f}"
                    )
                    return True
            except Exception as exc:
                delay = self.RETRY_BASE_DELAY ** (attempt + 1)
                logger.warning(
                    f"Tentative de connexion {attempt + 1}/{self.MAX_RETRIES} échouée: {exc}. "
                    f"Retry dans {delay}s..."
                )
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(delay)

        logger.error("Impossible de se connecter à Hyperliquid après plusieurs tentatives.")
        return False

    def _extract_balance(self, user_state: dict) -> float:
        """Extrait le solde total depuis l'état du compte."""
        try:
            margin_summary = user_state.get("marginSummary", {})
            return float(margin_summary.get("accountValue", 0))
        except (KeyError, ValueError, TypeError):
            return 0.0

    def get_user_state(self) -> Optional[dict]:
        """
        Récupère l'état complet du compte utilisateur.

        Returns:
            Dictionnaire avec les informations du compte ou None si erreur.
        """
        return self._call_with_retry(
            self.info.user_state, self.wallet_address
        )

    def get_all_mids(self) -> Optional[dict]:
        """
        Récupère les prix mid de tous les actifs.

        Returns:
            Dictionnaire {symbol: mid_price} ou None si erreur.
        """
        return self._call_with_retry(self.info.all_mids)

    def get_l2_book(self, symbol: str) -> Optional[dict]:
        """
        Récupère le carnet d'ordres (orderbook) niveau 2 pour un symbole.

        Args:
            symbol: Symbole de l'actif (ex: "BTC").

        Returns:
            Orderbook avec bids/asks ou None si erreur.
        """
        return self._call_with_retry(self.info.l2_book, symbol)

    def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: Optional[int] = None,
    ) -> Optional[list]:
        """
        Récupère les données OHLCV (bougies) historiques.

        Args:
            symbol: Symbole de l'actif.
            interval: Intervalle de temps ("1m", "5m", "15m", "1h", "4h", "1d").
            start_time: Timestamp de début en millisecondes.
            end_time: Timestamp de fin en millisecondes (défaut: maintenant).

        Returns:
            Liste de bougies OHLCV ou None si erreur.
        """
        if end_time is None:
            end_time = int(time.time() * 1000)

        return self._call_with_retry(
            self.info.candles_snapshot, symbol, interval, start_time, end_time
        )

    def get_open_orders(self) -> Optional[list]:
        """
        Récupère les ordres ouverts du compte.

        Returns:
            Liste des ordres ouverts ou None si erreur.
        """
        return self._call_with_retry(self.info.open_orders, self.wallet_address)

    def get_user_fills(self, start_time: Optional[int] = None) -> Optional[list]:
        """
        Récupère l'historique des transactions exécutées.

        Args:
            start_time: Timestamp de début en millisecondes.

        Returns:
            Liste des fills (transactions) ou None si erreur.
        """
        if start_time:
            return self._call_with_retry(
                self.info.user_fills_by_time, self.wallet_address, start_time
            )
        return self._call_with_retry(self.info.user_fills, self.wallet_address)

    def get_meta(self) -> Optional[dict]:
        """
        Récupère les métadonnées de tous les marchés (leverage max, tick size, etc.).

        Returns:
            Métadonnées des marchés ou None si erreur.
        """
        return self._call_with_retry(self.info.meta)

    def get_spot_meta(self) -> Optional[dict]:
        """
        Récupère les métadonnées des marchés spot.

        Returns:
            Métadonnées spot ou None si erreur.
        """
        return self._call_with_retry(self.info.spot_meta)

    def place_order(
        self,
        symbol: str,
        is_buy: bool,
        size: float,
        price: float,
        order_type: dict,
        reduce_only: bool = False,
    ) -> Optional[dict]:
        """
        Place un ordre sur le marché.

        Args:
            symbol: Symbole de l'actif.
            is_buy: True pour acheter, False pour vendre.
            size: Quantité à trader.
            price: Prix limite (0 pour ordre market).
            order_type: Type d'ordre (ex: {"limit": {"tif": "Gtc"}}).
            reduce_only: True pour ordre de réduction uniquement.

        Returns:
            Réponse de l'API avec les détails de l'ordre ou None si erreur.
        """
        return self._call_with_retry(
            self.exchange.order,
            symbol,
            is_buy,
            size,
            price,
            order_type,
            reduce_only=reduce_only,
        )

    def cancel_order(self, symbol: str, order_id: int) -> Optional[dict]:
        """
        Annule un ordre existant.

        Args:
            symbol: Symbole de l'actif.
            order_id: Identifiant de l'ordre.

        Returns:
            Confirmation d'annulation ou None si erreur.
        """
        return self._call_with_retry(self.exchange.cancel, symbol, order_id)

    def update_leverage(self, symbol: str, leverage: int, is_cross: bool = False) -> Optional[dict]:
        """
        Met à jour le levier pour un symbole perps.

        Args:
            symbol: Symbole de l'actif.
            leverage: Valeur du levier (1-100).
            is_cross: True pour cross margin, False pour isolated.

        Returns:
            Confirmation ou None si erreur.
        """
        return self._call_with_retry(
            self.exchange.update_leverage, leverage, symbol, is_cross
        )

    def _call_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Optional[Any]:
        """
        Appelle une fonction API avec retry et backoff exponentiel.

        Args:
            func: Fonction à appeler.
            *args: Arguments positionnels.
            **kwargs: Arguments nommés.

        Returns:
            Résultat de la fonction ou None si toutes les tentatives échouent.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                delay = self.RETRY_BASE_DELAY ** (attempt + 1)
                logger.warning(
                    f"Appel API {func.__name__} échoué (tentative {attempt + 1}/{self.MAX_RETRIES}): "
                    f"{exc}. Retry dans {delay}s..."
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(delay)
                else:
                    logger.error(f"Appel API {func.__name__} définitivement échoué: {exc}")

        return None

    @property
    def is_connected(self) -> bool:
        """Indique si le client est connecté."""
        return self._connected
