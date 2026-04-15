"""Hyperliquid Sniper Bot - Detects and trades price spikes across ALL cryptos.

Scans 150+ assets every few seconds, detects pumps/dumps,
waits for pullback confirmation, then enters with dynamic leverage.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

from core.client import HyperliquidClient
from core.scanner import PriceScanner
from core.executor import TradeExecutor

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format=(
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
))
logger.add(
    str(LOG_DIR / "sniper_{time:YYYY-MM-DD}.log"),
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
)


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        logger.error("config.yaml not found")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Dashboard (separate interface)
# ---------------------------------------------------------------------------

_bot_state: dict = {}


def set_state(state: dict) -> None:
    global _bot_state
    _bot_state = state


def run_dashboard(host: str, port: int) -> None:
    """Run a simple HTTP dashboard for the sniper bot."""
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import json

    class DashboardHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(_bot_state, default=str).encode())
                return

            if self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                dashboard_path = Path(__file__).parent / "dashboard.html"
                if dashboard_path.exists():
                    self.wfile.write(dashboard_path.read_bytes())
                else:
                    self.wfile.write(b"<h1>Sniper Bot - Dashboard not found</h1>")
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress HTTP logs

    server = HTTPServer((host, port), DashboardHandler)
    logger.info(f"Sniper dashboard: http://localhost:{port}")
    server.serve_forever()


# ---------------------------------------------------------------------------
# Sniper Bot
# ---------------------------------------------------------------------------


class SniperBot:
    """Main sniper bot - scans all cryptos for opportunities."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._running = False
        self._start_time = 0.0

        bot_cfg = config.get("bot", {})
        self._mode = bot_cfg.get("mode", "paper")
        self._scan_interval = bot_cfg.get("scan_interval", 3)
        self._paper_mode = self._mode == "paper"

        # Client
        self._client = HyperliquidClient()

        # Scanner with pullback parameters
        scan_cfg = config.get("scanner", {})
        pb_cfg = config.get("pullback", {})
        self._scanner = PriceScanner(
            min_spike_pct_1m=scan_cfg.get("min_spike_pct_1m", 1.5),
            min_spike_pct_5m=scan_cfg.get("min_spike_pct_5m", 3.0),
            min_spike_pct_15m=scan_cfg.get("min_spike_pct_15m", 5.0),
            blacklist=scan_cfg.get("blacklist", []),
            min_pullback_pct=pb_cfg.get("min_pullback_pct", 0.3),
            max_pullback_pct=pb_cfg.get("max_pullback_pct", 2.0),
            confirm_bounce_pct=pb_cfg.get("confirm_bounce_pct", 0.15),
            max_pullback_wait=pb_cfg.get("max_wait_seconds", 90),
        )
        self._scanner._signal_cooldown = scan_cfg.get("cooldown_seconds", 300)

        # Executor
        trade_cfg = config.get("trading", {})
        self._min_strength = trade_cfg.get("min_strength", 40)
        self._executor = TradeExecutor(
            client=self._client,
            paper_mode=self._paper_mode,
            risk_per_trade_pct=trade_cfg.get("risk_per_trade_pct", 2.0),
            max_open_trades=trade_cfg.get("max_open_trades", 3),
            tp_pct=trade_cfg.get("tp_pct", 2.0),
            sl_pct=trade_cfg.get("sl_pct", 1.0),
            max_hold_minutes=trade_cfg.get("max_hold_minutes", 5),
        )

        self._scan_count = 0

    def start(self) -> None:
        """Start the sniper bot."""
        load_dotenv()

        logger.info("=" * 50)
        logger.info("  HYPERLIQUID SNIPER BOT (PULLBACK MODE)")
        logger.info(f"  Mode: {self._mode.upper()}")
        logger.info(f"  Scanning ALL cryptos every {self._scan_interval}s")
        pb_cfg = self._config.get("pullback", {})
        logger.info(
            f"  Pullback: min={pb_cfg.get('min_pullback_pct', 0.3)}% "
            f"max={pb_cfg.get('max_pullback_pct', 2.0)}% "
            f"confirm={pb_cfg.get('confirm_bounce_pct', 0.15)}% "
            f"wait={pb_cfg.get('max_wait_seconds', 90)}s"
        )
        logger.info("=" * 50)

        self._client.connect()

        # Load balance
        if not self._paper_mode and self._client.is_connected:
            try:
                user_state = self._client.get_user_state()
                if user_state:
                    margin = user_state.get("marginSummary", {})
                    balance = float(margin.get("accountValue", 0))
                    if balance > 0:
                        self._executor.set_capital(balance)
                        logger.info(f"Balance loaded: ${balance:,.2f}")
                    else:
                        logger.warning("Balance is 0!")
            except Exception as e:
                logger.error(f"Failed to load balance: {e}")

        if self._paper_mode:
            self._executor.set_capital(10_000.0)
            logger.info("Paper mode: $10,000 virtual capital")

        # Count available assets
        mids = self._client.get_all_mids()
        logger.info(f"Monitoring {len(mids)} assets")

        # Dashboard
        dash_cfg = self._config.get("dashboard", {})
        if dash_cfg.get("enabled", True):
            host = dash_cfg.get("host", "0.0.0.0")
            port = dash_cfg.get("port", 8090)
            thread = threading.Thread(
                target=run_dashboard, args=(host, port), daemon=True
            )
            thread.start()

        # Main loop
        self._running = True
        self._start_time = time.time()

        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        except Exception as e:
            logger.exception(f"Fatal error: {e}")
        finally:
            self._running = False
            logger.info("Sniper bot stopped")

    def _run_loop(self) -> None:
        """Main scanning loop."""
        while self._running:
            try:
                loop_start = time.time()
                self._tick()

                # Update dashboard state
                set_state(self._build_state())

                elapsed = time.time() - loop_start
                sleep_time = max(0, self._scan_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Loop error: {e}")
                time.sleep(3)

    def _tick(self) -> None:
        """One scan cycle."""
        self._scan_count += 1

        # Get ALL prices
        mids = self._client.get_all_mids()
        if not mids:
            return

        # Scan for spikes (returns only pullback-confirmed signals)
        signals = self._scanner.update_prices(mids)

        # Check existing trades for TP/SL/expiry
        closed = self._executor.update_trades(mids)

        # Execute new signals
        for signal in signals:
            if signal.strength < self._min_strength:
                logger.debug(
                    f"Signal too weak: {signal.symbol} "
                    f"strength={signal.strength}% < {self._min_strength}%"
                )
                continue

            trade = self._executor.execute_signal(signal)
            if trade:
                logger.info(
                    f"NEW SNIPE: {trade.symbol} {trade.side} "
                    f"lev={trade.leverage}x strength={trade.strength}%"
                )

        # Periodic log
        if self._scan_count % 20 == 0:
            stats = self._executor.get_stats()
            pending = self._scanner.get_pending_pullbacks()
            top_movers = self._scanner.get_all_changes()[:5]
            movers_str = " | ".join(
                f"{m['symbol']} {m['change_1m']:+.1f}%"
                for m in top_movers
            )
            logger.info(
                f"Scan #{self._scan_count} | "
                f"{len(mids)} assets | "
                f"Pending: {len(pending)} | "
                f"Open: {stats['open_trades']} | "
                f"Trades: {stats['total_trades']} "
                f"(W:{stats['wins']} L:{stats['losses']}) | "
                f"PnL: ${stats['total_pnl']:+.2f} | "
                f"Top: {movers_str}"
            )

        # Cleanup
        if self._scan_count % 100 == 0:
            self._scanner.cleanup_cooldowns()

    def _build_state(self) -> dict:
        """Build state for dashboard."""
        stats = self._executor.get_stats()
        return {
            "mode": self._mode,
            "running": self._running,
            "scan_count": self._scan_count,
            "uptime": round(time.time() - self._start_time),
            "stats": stats,
            "pending_pullbacks": self._scanner.get_pending_pullbacks(),
            "open_trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "leverage": t.leverage,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "strength": t.strength,
                    "age": round(t.age_seconds),
                    "max_hold": t.max_hold_seconds,
                }
                for t in self._executor.get_open_trades()
            ],
            "recent_trades": self._executor.get_closed_trades(20),
            "top_movers": self._scanner.get_all_changes()[:20],
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    bot = SniperBot(config)
    bot.start()


if __name__ == "__main__":
    main()
