"""
Notifications Telegram — alertes sur événements critiques du bot.

Envoie des messages Telegram lors de l'ouverture/fermeture de trades,
des erreurs et des alertes de drawdown.
"""

import asyncio
from typing import Optional

from loguru import logger


class TelegramNotifier:
    """
    Gestionnaire de notifications Telegram.

    Envoie des alertes via l'API Bot Telegram pour les événements critiques.
    Désactivé si le token ou le chat_id ne sont pas configurés.
    """

    def __init__(self, bot_token: Optional[str], chat_id: Optional[str]) -> None:
        """
        Initialise le notificateur Telegram.

        Args:
            bot_token: Token du bot Telegram.
            chat_id: ID du chat destinataire.
        """
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

        if self._enabled:
            logger.info("Notifications Telegram activées.")
        else:
            logger.info("Notifications Telegram désactivées (token/chat_id manquants).")

    async def send(self, message: str) -> bool:
        """
        Envoie un message Telegram.

        Args:
            message: Texte du message (supporte le Markdown).

        Returns:
            True si envoyé avec succès, False sinon.
        """
        if not self._enabled:
            return False

        try:
            import httpx
            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            payload = {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return True

        except Exception as exc:
            logger.warning(f"Erreur notification Telegram: {exc}")
            return False

    async def notify_trade_opened(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
        is_paper: bool,
    ) -> None:
        """Notifie l'ouverture d'un trade."""
        mode = "🔵 PAPER" if is_paper else "🔴 LIVE"
        emoji = "📈" if side.lower() == "long" else "📉"

        message = (
            f"{emoji} *Trade Ouvert* {mode}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📌 Paire: `{symbol}`\n"
            f"📊 Côté: *{side.upper()}*\n"
            f"💰 Entrée: `${entry_price:,.4f}`\n"
            f"📦 Taille: `{size}`\n"
            f"🛑 Stop-Loss: `${stop_loss:,.4f}`\n"
            f"🎯 Take-Profit: `${take_profit:,.4f}`\n"
            f"🤖 Stratégie: `{strategy}`"
        )
        await self.send(message)

    async def notify_trade_closed(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        reason: str,
        strategy: str,
    ) -> None:
        """Notifie la fermeture d'un trade."""
        pnl_emoji = "✅" if pnl >= 0 else "❌"
        sign = "+" if pnl >= 0 else ""

        message = (
            f"{pnl_emoji} *Trade Fermé*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📌 Paire: `{symbol}` ({side.upper()})\n"
            f"💰 Entrée: `${entry_price:,.4f}`\n"
            f"💰 Sortie: `${exit_price:,.4f}`\n"
            f"💵 PnL: `{sign}${abs(pnl):.4f}` ({sign}{pnl_pct:.2f}%)\n"
            f"📝 Raison: `{reason}`\n"
            f"🤖 Stratégie: `{strategy}`"
        )
        await self.send(message)

    async def notify_drawdown_alert(
        self, current_drawdown: float, max_drawdown: float
    ) -> None:
        """Notifie une alerte de drawdown."""
        message = (
            f"⚠️ *Alerte Drawdown*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📉 Drawdown actuel: `{current_drawdown:.2f}%`\n"
            f"🛑 Limite: `{max_drawdown:.2f}%`\n"
            f"⚡ Le bot a été arrêté automatiquement."
        )
        await self.send(message)

    async def notify_error(self, error_message: str) -> None:
        """Notifie une erreur critique."""
        message = (
            f"🚨 *Erreur Bot*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"```\n{error_message[:500]}\n```"
        )
        await self.send(message)

    async def notify_bot_started(self, mode: str, capital: float) -> None:
        """Notifie le démarrage du bot."""
        message = (
            f"🚀 *HyperBot Démarré*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚙️ Mode: *{mode.upper()}*\n"
            f"💰 Capital: `${capital:,.2f}`"
        )
        await self.send(message)
