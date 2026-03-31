"""Telegram notification system for critical trading events."""

from __future__ import annotations

import os
from typing import Optional

import httpx
from loguru import logger

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Sends alerts via Telegram bot."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        self._token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._enabled = bool(self._token and self._chat_id)

        if not self._enabled:
            logger.info("Telegram notifications disabled (no token/chat_id)")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def send_message(self, text: str) -> bool:
        """Send a message to the configured Telegram chat."""
        if not self._enabled:
            return False

        url = TELEGRAM_API_URL.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    return True
                logger.warning(
                    f"Telegram API error: {response.status_code} - {response.text}"
                )
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

        return False

    async def notify_trade_opened(
        self, symbol: str, side: str, size: float, price: float, strategy: str
    ) -> None:
        """Notify about a new trade."""
        emoji = "\U0001f7e2" if side == "buy" else "\U0001f534"
        text = (
            f"{emoji} <b>Trade Opened</b>\n"
            f"Symbol: {symbol}\n"
            f"Side: {side.upper()}\n"
            f"Size: {size}\n"
            f"Price: {price}\n"
            f"Strategy: {strategy}"
        )
        await self.send_message(text)

    async def notify_trade_closed(
        self, symbol: str, pnl: float, pnl_pct: float, reason: str
    ) -> None:
        """Notify about a closed trade."""
        emoji = "\U0001f4b0" if pnl > 0 else "\U0001f4c9"
        text = (
            f"{emoji} <b>Trade Closed</b>\n"
            f"Symbol: {symbol}\n"
            f"PnL: {pnl:+.4f} ({pnl_pct:+.2f}%)\n"
            f"Reason: {reason}"
        )
        await self.send_message(text)

    async def notify_risk_alert(self, message: str) -> None:
        """Send a risk management alert."""
        text = f"\u26a0\ufe0f <b>RISK ALERT</b>\n{message}"
        await self.send_message(text)

    async def notify_bot_status(self, status: str, details: str = "") -> None:
        """Notify about bot status changes."""
        text = f"\U0001f916 <b>Bot Status: {status}</b>"
        if details:
            text += f"\n{details}"
        await self.send_message(text)
