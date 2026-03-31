"""Backtesting report generation."""

from __future__ import annotations

from loguru import logger

from backtesting.engine import BacktestResult


def generate_text_report(result: BacktestResult) -> str:
    """Generate a text-based performance report."""
    lines = [
        "=" * 60,
        f"  BACKTEST REPORT: {result.strategy_name.upper()}",
        "=" * 60,
        f"  Symbol:          {result.symbol}",
        f"  Timeframe:       {result.timeframe}",
        f"  Period:          {result.start_date} -> {result.end_date}",
        "-" * 60,
        "  PERFORMANCE",
        "-" * 60,
        f"  Initial Capital: ${result.initial_capital:,.2f}",
        f"  Final Capital:   ${result.final_capital:,.2f}",
        f"  Total Return:    {result.total_return_pct:+.2f}%",
        f"  Max Drawdown:    {result.max_drawdown_pct:.2f}%",
        f"  Sharpe Ratio:    {result.sharpe_ratio:.2f}",
        f"  Profit Factor:   {result.profit_factor:.2f}",
        "-" * 60,
        "  TRADES",
        "-" * 60,
        f"  Total Trades:    {result.total_trades}",
        f"  Winning:         {result.winning_trades}",
        f"  Losing:          {result.losing_trades}",
        f"  Win Rate:        {result.win_rate:.1f}%",
    ]

    if result.trades:
        avg_win = (
            sum(t.pnl for t in result.trades if t.pnl > 0)
            / max(result.winning_trades, 1)
        )
        avg_loss = (
            abs(sum(t.pnl for t in result.trades if t.pnl <= 0))
            / max(result.losing_trades, 1)
        )
        lines.extend([
            f"  Avg Win:         ${avg_win:,.4f}",
            f"  Avg Loss:        ${avg_loss:,.4f}",
        ])

    lines.append("=" * 60)
    return "\n".join(lines)


def generate_report_dict(result: BacktestResult) -> dict:
    """Generate report as dictionary for JSON/API response."""
    return {
        "strategy": result.strategy_name,
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "period": {
            "start": result.start_date,
            "end": result.end_date,
        },
        "performance": {
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "total_return_pct": result.total_return_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "profit_factor": result.profit_factor,
        },
        "trades": {
            "total": result.total_trades,
            "winning": result.winning_trades,
            "losing": result.losing_trades,
            "win_rate": result.win_rate,
        },
        "equity_curve": result.equity_curve,
        "trade_list": [
            {
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }


def print_report(result: BacktestResult) -> None:
    """Print report to console via loguru."""
    report = generate_text_report(result)
    for line in report.split("\n"):
        logger.info(line)
