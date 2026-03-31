"""Risk management - controls risk per trade, drawdown, and exposure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class RiskConfig:
    """Risk management configuration."""

    max_risk_per_trade_pct: float = 1.0
    max_drawdown_pct: float = 10.0
    max_open_positions: int = 5
    min_reward_risk_ratio: float = 2.0


class RiskManager:
    """Enforces risk rules before allowing trades."""

    def __init__(self, config: RiskConfig, initial_capital: float) -> None:
        self._config = config
        self._initial_capital = initial_capital
        self._peak_capital = initial_capital
        self._current_capital = initial_capital
        self._halted = False
        self._halt_reason = ""

    def update_capital(self, capital: float) -> None:
        """Update current capital and track peak for drawdown."""
        self._current_capital = capital
        if capital > self._peak_capital:
            self._peak_capital = capital

        drawdown_pct = self.current_drawdown_pct
        if drawdown_pct >= self._config.max_drawdown_pct:
            self._halted = True
            self._halt_reason = (
                f"Max drawdown reached: {drawdown_pct:.2f}% "
                f"(limit: {self._config.max_drawdown_pct}%)"
            )
            logger.error(f"RISK HALT: {self._halt_reason}")

    @property
    def current_drawdown_pct(self) -> float:
        """Calculate current drawdown from peak."""
        if self._peak_capital == 0:
            return 0.0
        return (
            (self._peak_capital - self._current_capital) / self._peak_capital
        ) * 100

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def reset_halt(self) -> None:
        """Manually reset the halt state."""
        self._halted = False
        self._halt_reason = ""
        logger.info("Risk halt reset manually")

    def can_open_position(self, open_position_count: int) -> bool:
        """Check if a new position can be opened."""
        if self._halted:
            logger.warning(f"Trading halted: {self._halt_reason}")
            return False

        if open_position_count >= self._config.max_open_positions:
            logger.warning(
                f"Max open positions reached: "
                f"{open_position_count}/{self._config.max_open_positions}"
            )
            return False

        return True

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        leverage: int = 1,
    ) -> float:
        """Calculate position size based on risk per trade and ATR-based stop.

        Uses: position_size = (capital * risk_pct) / |entry - stop_loss|
        """
        risk_amount = self._current_capital * (
            self._config.max_risk_per_trade_pct / 100
        )
        price_risk = abs(entry_price - stop_loss_price)

        if price_risk == 0:
            logger.warning("Zero price risk - cannot calculate position size")
            return 0.0

        size = risk_amount / price_risk

        # Ensure position value doesn't exceed capital with leverage
        max_notional = self._current_capital * leverage
        max_size = max_notional / entry_price
        size = min(size, max_size)

        return round(size, 6)

    def validate_stop_loss(
        self,
        entry_price: float,
        stop_loss: float,
        side: str,
    ) -> bool:
        """Validate stop-loss is on the correct side of entry price."""
        if side == "buy" and stop_loss >= entry_price:
            logger.warning("Stop-loss must be below entry for buy orders")
            return False
        if side == "sell" and stop_loss <= entry_price:
            logger.warning("Stop-loss must be above entry for sell orders")
            return False
        return True

    def validate_reward_risk(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> bool:
        """Validate the reward/risk ratio meets minimum requirements."""
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)

        if risk == 0:
            return False

        ratio = reward / risk
        if ratio < self._config.min_reward_risk_ratio:
            logger.warning(
                f"R:R ratio {ratio:.2f} below minimum "
                f"{self._config.min_reward_risk_ratio}"
            )
            return False

        return True

    def get_risk_summary(self) -> dict:
        """Return current risk state as a dictionary."""
        return {
            "initial_capital": self._initial_capital,
            "current_capital": self._current_capital,
            "peak_capital": self._peak_capital,
            "drawdown_pct": round(self.current_drawdown_pct, 2),
            "max_drawdown_pct": self._config.max_drawdown_pct,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
        }
