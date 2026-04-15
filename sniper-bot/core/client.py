"""Hyperliquid client for the Sniper Bot."""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

MAX_RETRIES = 3
RETRY_DELAY = 1.0


class HyperliquidClient:
    """Manages connection to Hyperliquid."""

    def __init__(self) -> None:
        self._private_key = os.getenv("HL_PRIVATE_KEY", "")
        self._account_address = os.getenv("HL_ACCOUNT_ADDRESS", "")
        self._info: Any = None
        self._exchange: Any = None
        self._connected = False

    def connect(self) -> None:
        """Connect to Hyperliquid mainnet."""
        try:
            from hyperliquid.info import Info

            base_url = "https://api.hyperliquid.xyz"
            self._info = Info(base_url, skip_ws=True)

            if self._private_key:
                try:
                    from hyperliquid.exchange import Exchange
                    from eth_account import Account

                    wallet = Account.from_key(self._private_key)
                    address = self._account_address or wallet.address
                    self._account_address = address
                    self._exchange = Exchange(
                        wallet, base_url, account_address=address
                    )
                    logger.info(f"Exchange authenticated: {address[:10]}...")
                except Exception as e:
                    logger.warning(f"Exchange init failed: {e}")

            self._connected = True
            mode = "authenticated" if self._exchange else "read-only"
            logger.info(f"Connected to Hyperliquid ({mode})")

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False

    def _retry(self, func: Any, *args: Any) -> Any:
        """API call with retry."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise
                logger.warning(f"API retry {attempt}: {e}")
                time.sleep(RETRY_DELAY * attempt)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def exchange(self) -> Any:
        return self._exchange

    @property
    def info(self) -> Any:
        return self._info

    def get_all_mids(self) -> dict[str, str]:
        """Get mid prices for ALL assets."""
        if not self._info:
            return {}
        return self._retry(self._info.all_mids)

    def get_meta(self) -> dict:
        """Get exchange metadata (all available assets)."""
        if not self._info:
            return {}
        return self._retry(self._info.meta)

    def get_user_state(self) -> dict:
        """Get account state."""
        if not self._info or not self._account_address:
            return {}
        return self._retry(self._info.user_state, self._account_address)

    def get_l2_book(self, symbol: str) -> dict:
        """Get order book for a symbol."""
        if not self._info:
            return {}
        return self._retry(self._info.l2_snapshot, symbol)
