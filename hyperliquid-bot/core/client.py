"""Hyperliquid API client - connection and authentication."""

import os
import time
from typing import Any, Optional

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# API retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


class HyperliquidClient:
    """Manages connection and authentication to the Hyperliquid exchange."""

    def __init__(self, testnet: bool = True) -> None:
        self._private_key = self._load_private_key()
        self._account_address = os.getenv("HL_ACCOUNT_ADDRESS", "")
        self._testnet = testnet
        self._info: Any = None
        self._exchange: Any = None
        self._connected = False

    @staticmethod
    def _load_private_key() -> str:
        """Load private key from environment. Never log or expose it."""
        key = os.getenv("HL_PRIVATE_KEY", "")
        if not key:
            logger.warning("HL_PRIVATE_KEY not set - running in read-only mode")
        return key

    def connect(self) -> None:
        """Establish connection to Hyperliquid API."""
        try:
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants

            base_url = (
                constants.TESTNET_API_URL if self._testnet
                else constants.MAINNET_API_URL
            )

            self._info = Info(base_url, skip_ws=True)

            if self._private_key:
                self._exchange = Exchange(
                    self._private_key,
                    base_url,
                    account_address=self._account_address or None,
                )

            self._connected = True
            mode = "testnet" if self._testnet else "MAINNET"
            logger.info(f"Connected to Hyperliquid ({mode})")

        except ImportError:
            logger.warning(
                "hyperliquid-python-sdk not installed - "
                "using paper trading simulation only"
            )
            self._connected = False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False

    def reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"Reconnection attempt {attempt}/{MAX_RETRIES}")
            self.connect()
            if self._connected:
                return
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            time.sleep(delay)
        logger.error("All reconnection attempts failed")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def info(self) -> Any:
        return self._info

    @property
    def exchange(self) -> Any:
        return self._exchange

    def _api_call_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute an API call with retry logic and exponential backoff."""
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(
                    f"API call failed (attempt {attempt}/{MAX_RETRIES}): {e}"
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    time.sleep(delay)
        raise ConnectionError(
            f"API call failed after {MAX_RETRIES} attempts: {last_error}"
        )

    def get_user_state(self, address: Optional[str] = None) -> dict:
        """Get account state including balances and positions."""
        addr = address or self._account_address
        if not self._info or not addr:
            return {}
        return self._api_call_with_retry(self._info.user_state, addr)

    def get_spot_balances(self, address: Optional[str] = None) -> list:
        """Get spot token balances."""
        addr = address or self._account_address
        if not self._info or not addr:
            return []
        try:
            return self._api_call_with_retry(
                self._info.spot_user_state, addr
            ).get("balances", [])
        except Exception as e:
            logger.error(f"Failed to get spot balances: {e}")
            return []

    def get_open_orders(self, address: Optional[str] = None) -> list:
        """Get all open orders."""
        addr = address or self._account_address
        if not self._info or not addr:
            return []
        return self._api_call_with_retry(self._info.open_orders, addr)

    def get_all_mids(self) -> dict[str, str]:
        """Get mid prices for all assets."""
        if not self._info:
            return {}
        return self._api_call_with_retry(self._info.all_mids)

    def get_candles(
        self, symbol: str, interval: str, limit: int = 500
    ) -> list[dict]:
        """Get OHLCV candle data for a symbol."""
        if not self._info:
            return []
        end_time = int(time.time() * 1000)
        interval_ms = self._interval_to_ms(interval)
        start_time = end_time - (limit * interval_ms)
        return self._api_call_with_retry(
            self._info.candles_snapshot, symbol, interval, start_time, end_time
        )

    def get_orderbook(self, symbol: str) -> dict:
        """Get current order book for a symbol."""
        if not self._info:
            return {}
        return self._api_call_with_retry(self._info.l2_snapshot, symbol)

    def get_meta(self) -> dict:
        """Get exchange metadata (available assets, etc.)."""
        if not self._info:
            return {}
        return self._api_call_with_retry(self._info.meta)

    @staticmethod
    def _interval_to_ms(interval: str) -> int:
        """Convert interval string to milliseconds."""
        multipliers = {
            "1m": 60_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        return multipliers.get(interval, 3_600_000)
