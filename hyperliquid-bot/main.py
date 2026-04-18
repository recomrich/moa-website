"""Hyperliquid Trading Bot - Main entry point.

Orchestrates all components: client, strategies, risk management,
order execution, and the real-time dashboard.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

from core.client import HyperliquidClient
from core.order_manager import Order, OrderManager, OrderSide, OrderType
from core.portfolio import Portfolio
from core.position_manager import Position, PositionManager
from core.risk_manager import RiskConfig, RiskManager
from dashboard.server import broadcast_update, run_dashboard, set_bot_state
from data.cache import DataCache
from data.feed import DataFeed
from database.repository import Repository
from strategies.base_strategy import Signal
from strategies.strategy_manager import StrategyManager

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format=(
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
    "<level>{message}</level>"
))
logger.add(
    str(LOG_DIR / "bot_{time:YYYY-MM-DD}.log"),
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        logger.error("config.yaml not found")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Bot class
# ---------------------------------------------------------------------------


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._running = False
        self._start_time = 0.0

        # Mode
        bot_cfg = config.get("bot", {})
        self._mode = bot_cfg.get("mode", "paper")
        self._update_interval = bot_cfg.get("update_interval", 60)
        self._paper_mode = self._mode == "paper"

        # Core components
        testnet = os.getenv("HL_TESTNET", "true").lower() == "true"
        self._client = HyperliquidClient(testnet=testnet)
        self._order_manager = OrderManager(self._client, paper_mode=self._paper_mode)
        # Position manager: allow multiple positions per crypto
        risk_cfg_pos = config.get("risk", {})
        self._position_manager = PositionManager(
            max_per_symbol=risk_cfg_pos.get("max_positions_per_symbol", 3),
            cooldown_minutes=risk_cfg_pos.get("cooldown_minutes", 30),
        )
        self._portfolio = Portfolio(initial_capital=10_000.0)

        # Risk
        risk_cfg = config.get("risk", {})
        risk_config = RiskConfig(
            max_risk_per_trade_pct=risk_cfg.get("max_risk_per_trade_pct", 1.0),
            max_drawdown_pct=risk_cfg.get("max_drawdown_pct", 10.0),
            max_open_positions=risk_cfg.get("max_open_positions", 5),
            min_reward_risk_ratio=risk_cfg.get("min_reward_risk_ratio", 2.0),
        )
        self._risk_manager = RiskManager(risk_config, self._portfolio.total_value)

        # Strategies
        self._strategy_manager = StrategyManager(config)

        # Data
        self._feed = DataFeed(self._client)
        self._cache = DataCache(ttl_seconds=30)

        # Database
        self._repository = Repository()

        # Build trading pairs list
        self._trading_pairs = self._build_trading_pairs()

    def _build_trading_pairs(self) -> list[dict]:
        """Build a flat list of trading pair configurations."""
        pairs = []
        tp_config = self._config.get("trading_pairs", {})

        for pair in tp_config.get("spot", []):
            pairs.append({
                "symbol": pair["symbol"],
                "is_perp": False,
                "leverage": 1,
                "strategies": pair.get("strategies", []),
            })

        for pair in tp_config.get("perps", []):
            pairs.append({
                "symbol": pair["symbol"],
                "is_perp": True,
                "leverage": pair.get("leverage", 1),
                "strategies": pair.get("strategies", []),
            })

        return pairs

    def _get_bot_state(self) -> dict:
        """Build shared state dict for the dashboard."""
        return {
            "mode": self._mode,
            "running": self._running,
            "portfolio": self._portfolio,
            "risk_manager": self._risk_manager,
            "position_manager": self._position_manager,
            "strategy_manager": self._strategy_manager,
            "feed": self._feed,
            "repository": self._repository,
            "uptime": time.time() - self._start_time if self._start_time else 0,
        }

    def start(self) -> None:
        """Start the trading bot."""
        load_dotenv()
        logger.info("=" * 50)
        logger.info("  HYPERLIQUID TRADING BOT")
        logger.info(f"  Mode: {self._mode.upper()}")
        logger.info("=" * 50)

        # Connect to exchange
        self._client.connect()

        # Fetch real balance in live mode
        if not self._paper_mode and self._client.is_connected:
            try:
                real_balance = 0.0

                # Check Perps balance
                user_state = self._client.get_user_state()
                if user_state:
                    margin = user_state.get("marginSummary", {})
                    real_balance = float(margin.get("accountValue", 0))

                # Check Spot balance (USDC)
                spot_balance = 0.0
                spot_balances = self._client.get_spot_balances()
                for bal in spot_balances:
                    if bal.get("coin") == "USDC":
                        spot_balance = float(bal.get("total", 0))
                        break

                total = real_balance + spot_balance
                logger.info(f"Perps balance: ${real_balance:,.2f} | Spot USDC: ${spot_balance:,.2f} | Total: ${total:,.2f}")

                if total > 0:
                    self._portfolio = Portfolio(initial_capital=total)
                    risk_cfg = self._config.get("risk", {})
                    self._risk_manager = RiskManager(
                        RiskConfig(
                            max_risk_per_trade_pct=risk_cfg.get("max_risk_per_trade_pct", 1.0),
                            max_drawdown_pct=risk_cfg.get("max_drawdown_pct", 10.0),
                            max_open_positions=risk_cfg.get("max_open_positions", 5),
                            min_reward_risk_ratio=risk_cfg.get("min_reward_risk_ratio", 2.0),
                        ),
                        initial_capital=total,
                    )
                    logger.info(f"Real balance loaded: ${total:,.2f}")
                else:
                    logger.warning("Account balance is 0 - check your wallet")
            except Exception as e:
                logger.error(f"Failed to load balance: {e}")

        # Share state with dashboard
        set_bot_state(self._get_bot_state())

        # Start dashboard in background thread
        dash_cfg = self._config.get("dashboard", {})
        if dash_cfg.get("enabled", True):
            host = dash_cfg.get("host", os.getenv("DASHBOARD_HOST", "0.0.0.0"))
            port = dash_cfg.get("port", int(os.getenv("DASHBOARD_PORT", "8080")))
            dash_thread = threading.Thread(
                target=run_dashboard, args=(host, port), daemon=True
            )
            dash_thread.start()
            logger.info(f"Dashboard available at http://localhost:{port}")

        # Validate trading pairs against available symbols
        self._validate_trading_pairs()

        # Main trading loop
        self._running = True
        self._start_time = time.time()
        logger.info("Bot started - entering main loop")

        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user")
        except Exception as e:
            logger.exception(f"Fatal error: {e}")
        finally:
            self._running = False
            logger.info("Bot stopped")

    def _validate_trading_pairs(self) -> None:
        """Check which configured symbols are available on the exchange.

        Removes unavailable symbols and logs warnings.
        """
        available = self._feed.get_available_symbols()
        if not available:
            logger.warning("Could not fetch available symbols - skipping validation")
            return

        logger.info(f"Exchange has {len(available)} available symbols")

        valid_pairs = []
        for pair in self._trading_pairs:
            symbol = pair["symbol"]
            if symbol in available:
                valid_pairs.append(pair)
            else:
                logger.warning(
                    f"Symbol '{symbol}' not found on exchange - removing from trading pairs. "
                    f"Available similar: {[s for s in available if symbol.lower() in s.lower()]}"
                )

        removed = len(self._trading_pairs) - len(valid_pairs)
        if removed > 0:
            logger.info(f"Removed {removed} unavailable pairs, {len(valid_pairs)} pairs active")
        self._trading_pairs = valid_pairs

    def _run_loop(self) -> None:
        """Main trading loop."""
        while self._running:
            try:
                loop_start = time.time()
                self._tick()
                # Update shared state for dashboard
                set_bot_state(self._get_bot_state())

                elapsed = time.time() - loop_start
                sleep_time = max(0, self._update_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)

    def _tick(self) -> None:
        """Execute one analysis cycle."""
        # 1. Update prices
        prices = self._feed.get_current_prices()
        if not prices:
            logger.warning("No price data available - check connection")
            return

        # Log key prices
        tracked_symbols = [p["symbol"] for p in self._trading_pairs]
        price_info = {s: f"${prices[s]:,.2f}" for s in tracked_symbols if s in prices}
        logger.info(f"Prices: {price_info}")

        # 2. Check SL/TP triggers and trailing stop updates
        triggered, sl_updated = self._position_manager.update_prices(prices)

        # Handle positions whose trailing SL moved -> update on exchange
        for pos_id in sl_updated:
            pos = self._position_manager.get_position(pos_id)
            if pos and pos.stop_loss:
                new_oid = self._order_manager.update_stop_loss(
                    pos.symbol, pos.side, pos.size,
                    pos.sl_order_id, pos.stop_loss,
                )
                if new_oid:
                    pos.sl_order_id = new_oid
                    logger.info(
                        f"Trailing SL updated on exchange: {pos.symbol} "
                        f"new SL={pos.stop_loss}"
                    )

        # Handle triggered SL/TP
        for pos_id in triggered:
            pos = self._position_manager.get_position(pos_id)
            if pos:
                # Cancel remaining TP or SL order on exchange
                if pos.tp_order_id:
                    self._order_manager.cancel_trigger_order(
                        pos.symbol, pos.tp_order_id
                    )
                if pos.sl_order_id:
                    self._order_manager.cancel_trigger_order(
                        pos.symbol, pos.sl_order_id
                    )

                exit_price = prices.get(pos.symbol, pos.entry_price)
                result = self._position_manager.close_position(
                    pos_id, exit_price, reason="sl_tp_triggered"
                )
                if result:
                    self._portfolio.record_trade(result)
                    self._repository.save_trade(result)
                    won = result.get("pnl", 0) > 0
                    strategy = self._strategy_manager.get_strategy(pos.strategy_name)
                    if strategy:
                        strategy.record_result(won)

        # 3. Update portfolio
        self._portfolio.check_new_day()
        unrealized = self._position_manager.get_total_unrealized_pnl()
        self._portfolio.update_paper(unrealized)
        self._risk_manager.update_capital(self._portfolio.total_value)

        # 4. Check if risk halt
        if self._risk_manager.is_halted:
            logger.warning("Trading halted by risk manager")
            return

        # 5. Run strategies for each trading pair
        for pair in self._trading_pairs:
            self._process_pair(pair, prices)

    def _process_pair(self, pair: dict, prices: dict[str, float]) -> None:
        """Process strategies for a single trading pair using consensus.

        All strategies vote first, then only open a position if 2+ agree.
        This prevents 5 separate positions on the same symbol.
        """
        symbol = pair["symbol"]
        is_perp = pair["is_perp"]
        leverage = pair["leverage"]
        pair_strategies = pair["strategies"]

        if not self._position_manager.can_open_for_symbol(symbol):
            return

        if not self._risk_manager.can_open_position(
            self._position_manager.open_count
        ):
            return

        from strategies.strategy_manager import CONFIRMATION_TIMEFRAMES

        buy_votes: list[tuple[str, int]] = []
        sell_votes: list[tuple[str, int]] = []
        best_strategy_name = None
        best_confidence = 0

        for strategy_name in pair_strategies:
            strategy = self._strategy_manager.get_strategy(strategy_name)
            if not strategy or not strategy.enabled:
                continue

            df = self._cache.get_or_fetch(
                symbol, strategy.timeframe, self._feed.get_ohlcv
            )
            if df.empty:
                continue

            htf = CONFIRMATION_TIMEFRAMES.get(strategy.timeframe)
            higher_tf_df = None
            if htf:
                higher_tf_df = self._cache.get_or_fetch(
                    symbol, htf, self._feed.get_ohlcv
                )

            signal, confidence = self._strategy_manager.run_with_confirmation(
                strategy_name, df, higher_tf_df, symbol
            )
            logger.info(
                f"[{strategy_name}] {symbol} ({strategy.timeframe}) -> "
                f"{signal.value if signal else 'ERROR'} "
                f"(confidence={confidence}%)"
            )
            if signal is None or signal == Signal.HOLD:
                continue

            self._repository.save_strategy_run(
                strategy_name, symbol, strategy.timeframe, signal.value
            )

            if signal == Signal.BUY:
                buy_votes.append((strategy_name, confidence))
            elif signal == Signal.SELL:
                sell_votes.append((strategy_name, confidence))

        min_votes = 2
        chosen_signal = None
        votes = []

        if len(buy_votes) >= min_votes and len(buy_votes) >= len(sell_votes):
            chosen_signal = Signal.BUY
            votes = buy_votes
        elif len(sell_votes) >= min_votes:
            chosen_signal = Signal.SELL
            votes = sell_votes

        if chosen_signal is None:
            if buy_votes:
                logger.debug(
                    f"[CONSENSUS] {symbol}: only {len(buy_votes)} BUY vote(s), need {min_votes}"
                )
            if sell_votes:
                logger.debug(
                    f"[CONSENSUS] {symbol}: only {len(sell_votes)} SELL vote(s), need {min_votes}"
                )
            return

        best_strategy_name = max(votes, key=lambda x: x[1])[0]
        avg_confidence = sum(c for _, c in votes) // len(votes)
        strategy = self._strategy_manager.get_strategy(best_strategy_name)

        logger.info(
            f"[CONSENSUS] {symbol} {chosen_signal.value} confirmed by "
            f"{len(votes)} strategies: {[v[0] for v in votes]} "
            f"(avg confidence={avg_confidence}%)"
        )

        df = self._cache.get_or_fetch(
            symbol, strategy.timeframe, self._feed.get_ohlcv
        )

        actual_leverage = self._calculate_leverage(
            leverage, avg_confidence, is_perp
        )

        self._execute_signal(
            chosen_signal, symbol, strategy, df, is_perp, actual_leverage
        )

    def _calculate_leverage(
        self, base_leverage: int, confidence: int, is_perp: bool
    ) -> int:
        """Calculate dynamic leverage based on signal confidence.

        Conservative tiers:
            85-100% -> base leverage from config (3x)
            70-84%  -> base leverage (3x)
            50-69%  -> reduced (2x)
            <50%    -> minimum (1x)

        Only applies to perps. Spot always uses 1x.
        """
        if not is_perp:
            return 1

        if confidence >= 70:
            lev = base_leverage
        elif confidence >= 50:
            lev = max(1, base_leverage - 1)
        else:
            lev = 1

        logger.info(
            f"Leverage: confidence={confidence}% -> {lev}x (base={base_leverage}x)"
        )
        return lev

    def _execute_signal(
        self,
        signal: Signal,
        symbol: str,
        strategy: object,
        df: object,
        is_perp: bool,
        leverage: int,
    ) -> None:
        """Execute a trading signal."""
        from indicators.volatility import atr as calc_atr

        current_price = self._feed.get_price(symbol)
        if not current_price:
            return

        # Get ATR for position sizing
        atr_series = calc_atr(df)
        current_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0
        if current_atr == 0:
            return

        side_str = "buy" if signal == Signal.BUY else "sell"
        side = OrderSide.BUY if signal == Signal.BUY else OrderSide.SELL

        # Calculate SL/TP
        sl = strategy.get_stop_loss(current_price, current_atr, side_str)
        tp = strategy.get_take_profit(current_price, current_atr, side_str)

        # Validate risk
        if not self._risk_manager.validate_stop_loss(current_price, sl, side_str):
            return
        if not self._risk_manager.validate_reward_risk(current_price, sl, tp):
            return

        # Calculate position size
        size = self._risk_manager.calculate_position_size(
            current_price, sl, leverage
        )
        if size <= 0:
            return

        # Place order
        order = Order(
            symbol=symbol,
            side=side,
            size=size,
            order_type=OrderType.MARKET,
            stop_loss=sl,
            take_profit=tp,
            leverage=leverage,
            is_perp=is_perp,
        )

        filled_order = self._order_manager.place_order(order)

        if filled_order.fill_price:
            # Place TP/SL trigger orders on the exchange
            sl_oid, tp_oid = self._order_manager.place_tp_sl(
                symbol, side, filled_order.size or size, sl, tp,
            )

            # Record position with exchange TP/SL order IDs
            position = Position(
                symbol=symbol,
                side=side,
                size=size,
                entry_price=filled_order.fill_price,
                leverage=leverage,
                is_perp=is_perp,
                stop_loss=sl,
                take_profit=tp,
                strategy_name=strategy.name,
                sl_order_id=sl_oid,
                tp_order_id=tp_oid,
            )
            self._position_manager.open_position(position)

            logger.info(
                f"TP/SL placed on exchange: SL={sl} (oid={sl_oid}) "
                f"TP={tp} (oid={tp_oid})"
            )

            # Save order to DB
            self._repository.save_order({
                "order_id": filled_order.order_id,
                "symbol": symbol,
                "side": side.value,
                "order_type": filled_order.order_type.value,
                "size": size,
                "price": filled_order.price,
                "fill_price": filled_order.fill_price,
                "status": filled_order.status.value,
                "strategy": strategy.name,
            })

    async def _broadcast_updates(self) -> None:
        """Broadcast current state to dashboard WebSocket clients."""
        await broadcast_update("status", {
            "mode": self._mode,
            "running": self._running,
            "portfolio": self._portfolio.get_summary(),
            "risk": self._risk_manager.get_risk_summary(),
        })

        positions = self._position_manager.get_all_positions()
        await broadcast_update("positions", [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "size": p.size,
                "entry_price": p.entry_price,
                "unrealized_pnl": round(p.unrealized_pnl, 4),
                "pnl_pct": p.pnl_pct,
                "leverage": p.leverage,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "strategy": p.strategy_name,
            }
            for p in positions
        ])

        await broadcast_update(
            "strategies",
            self._strategy_manager.get_all_statuses()
        )

        await broadcast_update("equity", self._portfolio.get_equity_curve(200))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    config = load_config()
    bot = TradingBot(config)
    bot.start()


if __name__ == "__main__":
    main()
