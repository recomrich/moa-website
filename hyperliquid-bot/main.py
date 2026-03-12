"""
Point d'entrée principal de HyperBot.

Orchestre tous les composants du bot : connexion Hyperliquid,
récupération des données, exécution des stratégies, gestion du risque
et dashboard web temps réel.

Usage:
    python main.py                    # Démarre le bot
    python main.py --backtest         # Mode backtesting
    python main.py --check-config     # Vérifie la configuration
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import uvicorn
import yaml
from dotenv import load_dotenv
from loguru import logger

# ─── Chargement de la configuration ──────────────────────────────────────────

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")

# Rotation des logs
logger.remove()
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
)
logger.add(
    LOG_FILE,
    level=LOG_LEVEL,
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
)

# ─── Imports après configuration des logs ────────────────────────────────────

from core.client import HyperliquidClient
from core.order_manager import OrderManager
from core.portfolio import Portfolio
from core.position_manager import PositionManager
from core.risk_manager import RiskConfig, RiskManager
from dashboard.server import app, broadcast_update, set_bot_reference
from data.cache import DataCache
from data.feed import DataFeed
from data.historical import HistoricalData
from database.repository import TradingRepository
from notifications.telegram import TelegramNotifier
from strategies.base_strategy import Signal, TradeSignal
from strategies.strategy_manager import StrategyManager


def load_config(config_path: str = "config.yaml") -> dict:
    """
    Charge la configuration depuis le fichier YAML.

    Args:
        config_path: Chemin vers config.yaml.

    Returns:
        Dictionnaire de configuration.

    Raises:
        FileNotFoundError: Si le fichier de configuration n'existe pas.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier de configuration non trouvé: {config_path}")

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class TradingBot:
    """
    Bot de trading principal — orchestre tous les composants.

    Gère le cycle de vie complet : initialisation, boucle principale,
    traitement des signaux et arrêt propre.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialise le bot avec la configuration fournie.

        Args:
            config: Configuration complète depuis config.yaml.
        """
        self.config = config
        self.bot_config = config.get("bot", {})
        self.paper_mode = self.bot_config.get("mode", "paper") == "paper"
        self.is_running = False
        self._start_time = time.time()

        self._validate_env()
        self._init_components()

    @property
    def uptime_seconds(self) -> float:
        """Durée de fonctionnement en secondes."""
        return time.time() - self._start_time

    def _validate_env(self) -> None:
        """Valide que les variables d'environnement requises sont présentes."""
        required = ["HYPERLIQUID_PRIVATE_KEY", "HYPERLIQUID_WALLET_ADDRESS"]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            logger.warning(
                f"Variables d'environnement manquantes: {missing}. "
                f"Utilisation de valeurs par défaut (paper trading uniquement)."
            )

    def _init_components(self) -> None:
        """Instancie tous les composants du bot."""
        private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "0" * 64)
        wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "0x" + "0" * 40)
        network = os.getenv("HYPERLIQUID_NETWORK", "mainnet")

        # Core
        self.client = HyperliquidClient(private_key, wallet_address, network)
        self.order_manager = OrderManager(self.client, paper_mode=self.paper_mode)

        # Risk
        risk_config_data = self.config.get("risk", {})
        risk_config = RiskConfig(
            max_risk_per_trade_pct=risk_config_data.get("max_risk_per_trade_pct", 1.0),
            max_drawdown_pct=risk_config_data.get("max_drawdown_pct", 10.0),
            max_open_positions=risk_config_data.get("max_open_positions", 5),
            min_risk_reward_ratio=risk_config_data.get("min_risk_reward_ratio", 2.0),
        )
        self.risk_manager = RiskManager(risk_config)

        # Data
        self.cache = DataCache()
        self.historical = HistoricalData(self.client, self.cache)
        self.data_feed = DataFeed(self.client, self.cache, self.historical)

        # Portfolio
        paper_config = self.config.get("paper_trading", {})
        initial_capital = (
            paper_config.get("initial_capital", 10_000.0)
            if self.paper_mode
            else 0.0
        )
        self.portfolio = Portfolio(self.client, initial_capital, paper_mode=self.paper_mode)
        self.risk_manager.initialize_capital(initial_capital)

        # Positions
        self.position_manager = PositionManager(
            self.client, self.order_manager, paper_mode=self.paper_mode
        )

        # Database
        self.repository = TradingRepository()

        # Strategies
        self.strategy_manager = StrategyManager(
            config=self.config,
            data_feed=self.data_feed,
            signal_callback=self._on_signal,
        )

        # Notifications
        telegram_config = self.config.get("notifications", {}).get("telegram", {})
        self.notifier = TelegramNotifier(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        ) if telegram_config.get("enabled", False) else TelegramNotifier(None, None)

        # Abonnement aux prix pour mettre à jour les positions
        self.data_feed.subscribe_prices(self._on_price_update)

        logger.info(
            f"Bot initialisé — mode: {'PAPER' if self.paper_mode else 'LIVE'} | "
            f"capital: ${initial_capital:,.2f}"
        )

    async def start(self) -> None:
        """Démarre le bot et toutes ses boucles async."""
        self.is_running = True
        logger.info("=" * 60)
        logger.info("  HYPERBOT DÉMARRÉ")
        logger.info(f"  Mode    : {'PAPER TRADING' if self.paper_mode else '⚠️  LIVE TRADING'}")
        logger.info(f"  Network : {os.getenv('HYPERLIQUID_NETWORK', 'mainnet')}")
        logger.info("=" * 60)

        connected = await self.client.connect()
        if not connected and not self.paper_mode:
            logger.error("Connexion échouée en mode live. Arrêt.")
            return

        await self.notifier.notify_bot_started(
            "PAPER" if self.paper_mode else "LIVE",
            self.portfolio.get_current_equity(),
        )

        # Lancement parallèle de toutes les boucles
        await asyncio.gather(
            self._data_feed_loop(),
            self._strategy_loop(),
            self._equity_update_loop(),
            self._dashboard_broadcast_loop(),
            return_exceptions=True,
        )

    async def _data_feed_loop(self) -> None:
        """Boucle de mise à jour des prix (toutes les 5 secondes)."""
        await self.data_feed.start(update_interval=5.0)

    async def _strategy_loop(self) -> None:
        """Boucle principale d'analyse des stratégies."""
        interval = self.bot_config.get("update_interval", 60)
        logger.info(f"Boucle stratégies démarrée — intervalle: {interval}s")

        # Attente initiale pour que les données soient disponibles
        await asyncio.sleep(10)

        while self.is_running:
            try:
                if not self.risk_manager.is_bot_stopped:
                    signals = await self.strategy_manager.run_cycle()
                    if signals:
                        logger.debug(f"{len(signals)} signaux actionnables générés.")
                else:
                    logger.warning("Bot arrêté (drawdown max). Aucun nouveau trade.")

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Erreur boucle stratégies: {exc}", exc_info=True)
                await self.notifier.notify_error(str(exc))
                await asyncio.sleep(interval)

    async def _equity_update_loop(self) -> None:
        """Boucle de mise à jour de l'équity (toutes les 60 secondes)."""
        while self.is_running:
            try:
                unrealized_pnl = self.position_manager.get_total_unrealized_pnl()
                self.portfolio.update_equity(unrealized_pnl)

                equity = self.portfolio.get_current_equity()
                self.risk_manager.update_capital(equity)

                # Snapshot en base
                self.repository.save_equity_snapshot(
                    equity=equity,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl_today=self.portfolio.get_daily_pnl(),
                    open_positions=self.position_manager.get_positions_count(),
                    is_paper=self.paper_mode,
                )

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Erreur boucle équity: {exc}")
                await asyncio.sleep(60)

    async def _dashboard_broadcast_loop(self) -> None:
        """Boucle de diffusion WebSocket vers le dashboard."""
        dashboard_config = self.config.get("dashboard", {})
        interval_ms = dashboard_config.get("update_interval_ms", 1000)
        interval_s = interval_ms / 1000

        while self.is_running:
            try:
                await broadcast_update("positions", self.position_manager.to_dict_list())
                await broadcast_update("portfolio", self.portfolio.get_summary())
                await broadcast_update("risk", self.risk_manager.get_stats())
                await broadcast_update("strategies", self.strategy_manager.get_all_stats())

                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(f"Erreur broadcast dashboard: {exc}")
                await asyncio.sleep(interval_s)

    def _on_signal(self, signal: TradeSignal, market_type: str) -> None:
        """
        Callback appelé pour chaque signal actionnable.

        Vérifie les règles de risque et exécute l'ordre si approuvé.

        Args:
            signal: Signal de trading.
            market_type: "spot" ou "perps".
        """
        if signal.signal == Signal.HOLD:
            return

        # Sauvegarde du signal en base
        self.repository.save_strategy_run(
            strategy_name=signal.strategy_name,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            signal=signal.signal.value,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence=signal.confidence,
            reason=signal.reason,
        )

        # Vérification du risque
        risk_check = self.risk_manager.check_new_trade(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            current_positions_count=self.position_manager.get_positions_count(),
        )

        if not risk_check.approved:
            logger.info(
                f"Signal refusé [{signal.strategy_name}] {signal.symbol}: {risk_check.reason}"
            )
            return

        # Exécution de l'ordre
        from core.order_manager import OrderSide

        side = OrderSide.BUY if signal.signal == Signal.BUY else OrderSide.SELL
        size = risk_check.position_size

        order = self.order_manager.create_market_order(
            symbol=signal.symbol,
            side=side,
            size=size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy_name=signal.strategy_name,
            current_price=signal.entry_price,
        )

        if order and (order.filled_size > 0 or self.paper_mode):
            position = self.position_manager.open_position(order)
            if position:
                # Sauvegarde en base
                self.repository.save_trade(
                    trade_id=order.id,
                    symbol=signal.symbol,
                    side="long" if side == OrderSide.BUY else "short",
                    entry_price=order.avg_fill_price or signal.entry_price,
                    size=order.filled_size or size,
                    strategy_name=signal.strategy_name,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    market_type=market_type,
                    is_paper=self.paper_mode,
                )

                asyncio.create_task(
                    self.notifier.notify_trade_opened(
                        symbol=signal.symbol,
                        side="long" if side == OrderSide.BUY else "short",
                        entry_price=order.avg_fill_price or signal.entry_price,
                        size=order.filled_size or size,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        strategy=signal.strategy_name,
                        is_paper=self.paper_mode,
                    )
                )

    def _on_price_update(self, prices: dict[str, float]) -> None:
        """
        Callback appelé à chaque mise à jour des prix.

        Vérifie les SL/TP et ferme les positions déclenchées.

        Args:
            prices: Dictionnaire {symbol: price}.
        """
        closed = self.position_manager.update_prices(prices)

        for pos_id, pnl, reason in closed:
            self.risk_manager.record_trade_result(pnl)
            self.risk_manager.update_capital(
                self.portfolio.get_current_equity() + pnl
            )

            logger.info(
                f"Position fermée [{reason}]: {pos_id} | PnL: ${pnl:+.4f}"
            )

            asyncio.create_task(
                self.notifier.notify_trade_closed(
                    symbol="",
                    side="",
                    entry_price=0,
                    exit_price=prices.get("", 0),
                    pnl=pnl,
                    pnl_pct=0,
                    reason=reason,
                    strategy="",
                )
            )

    def stop(self) -> None:
        """Arrête proprement le bot."""
        self.is_running = False
        self.data_feed.stop()
        logger.info("Bot arrêté.")


async def run_bot(config: dict) -> None:
    """Lance le bot et le serveur dashboard en parallèle."""
    bot = TradingBot(config)
    set_bot_reference(bot)

    dashboard_host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    dashboard_port = int(os.getenv("DASHBOARD_PORT", 8080))

    # Configuration uvicorn
    server_config = uvicorn.Config(
        app=app,
        host=dashboard_host,
        port=dashboard_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_config)

    logger.info(f"Dashboard: http://localhost:{dashboard_port}")

    # Gestion du signal d'arrêt
    def handle_shutdown(sig, frame):
        logger.info(f"Signal {sig} reçu — arrêt en cours...")
        bot.stop()
        server.should_exit = True

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    await asyncio.gather(
        bot.start(),
        server.serve(),
    )


def check_config(config: dict) -> None:
    """Vérifie et affiche la configuration."""
    print("\n✅ Configuration chargée avec succès:")
    print(f"   Mode     : {config.get('bot', {}).get('mode', 'paper').upper()}")
    print(f"   Interval : {config.get('bot', {}).get('update_interval', 60)}s")

    risk = config.get("risk", {})
    print(f"   Risk/trade: {risk.get('max_risk_per_trade_pct', 1)}%")
    print(f"   Max DD    : {risk.get('max_drawdown_pct', 10)}%")

    strategies_config = config.get("strategies", {})
    enabled = [k for k, v in strategies_config.items() if v.get("enabled", False)]
    print(f"   Stratégies actives: {', '.join(enabled) if enabled else 'aucune'}")

    pairs_spot = config.get("trading_pairs", {}).get("spot", [])
    pairs_perps = config.get("trading_pairs", {}).get("perps", [])
    print(f"   Paires spot : {[p['symbol'] for p in pairs_spot]}")
    print(f"   Paires perps: {[p['symbol'] for p in pairs_perps]}")
    print()


def main() -> None:
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(description="HyperBot — Bot de trading Hyperliquid")
    parser.add_argument(
        "--config", default="config.yaml", help="Chemin vers config.yaml"
    )
    parser.add_argument(
        "--check-config", action="store_true", help="Vérifier la configuration et quitter"
    )
    parser.add_argument(
        "--backtest", action="store_true", help="Lancer en mode backtesting"
    )
    parser.add_argument(
        "--strategy", default="trend_following", help="Stratégie à backtester"
    )
    parser.add_argument(
        "--symbol", default="BTC", help="Symbole à backtester"
    )
    parser.add_argument(
        "--days", type=int, default=90, help="Nombre de jours d'historique"
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)

    if args.check_config:
        check_config(config)
        return

    if args.backtest:
        _run_backtest(config, args.strategy, args.symbol, args.days)
        return

    # Lancement normal du bot
    try:
        asyncio.run(run_bot(config))
    except KeyboardInterrupt:
        logger.info("Arrêt par l'utilisateur.")
    except Exception as exc:
        logger.critical(f"Erreur fatale: {exc}", exc_info=True)
        sys.exit(1)


def _run_backtest(config: dict, strategy_name: str, symbol: str, days: int) -> None:
    """Lance le backtesting d'une stratégie."""
    from datetime import timedelta

    from backtesting.engine import BacktestEngine
    from backtesting.report import generate_report
    from core.client import HyperliquidClient
    from data.cache import DataCache
    from data.historical import HistoricalData
    from strategies.strategy_manager import STRATEGY_REGISTRY

    logger.info(f"Démarrage du backtesting: {strategy_name} sur {symbol} ({days}j)")

    strategy_class = STRATEGY_REGISTRY.get(strategy_name)
    if not strategy_class:
        logger.error(f"Stratégie inconnue: {strategy_name}. Disponibles: {list(STRATEGY_REGISTRY.keys())}")
        return

    strategy_config = config.get("strategies", {}).get(strategy_name, {})
    strategy_config["enabled"] = True
    strategy = strategy_class(strategy_config)

    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "0" * 64)
    wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "0x" + "0" * 40)
    network = os.getenv("HYPERLIQUID_NETWORK", "mainnet")

    client = HyperliquidClient(private_key, wallet_address, network)
    cache = DataCache()
    historical = HistoricalData(client, cache)

    end_date = datetime.utcnow() if False else None
    start_date = datetime.utcnow() - timedelta(days=days)

    from datetime import datetime as dt
    df = historical.get_ohlcv_range(symbol, strategy.timeframe, start_date)

    if df is None or df.empty:
        logger.error(f"Impossible de récupérer les données pour {symbol} {strategy.timeframe}")
        return

    initial_capital = config.get("paper_trading", {}).get("initial_capital", 10_000.0)
    risk_pct = config.get("risk", {}).get("max_risk_per_trade_pct", 1.0)

    engine = BacktestEngine(strategy, initial_capital=initial_capital, risk_pct=risk_pct)
    result = engine.run(df, symbol)

    generate_report(result, output_dir="backtesting/reports")


if __name__ == "__main__":
    main()
