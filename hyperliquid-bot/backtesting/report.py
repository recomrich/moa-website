"""
Générateur de rapports de backtesting — métriques et visualisations.

Produit un rapport complet au format texte/JSON avec les métriques
de performance clés (Sharpe, Sortino, drawdown, etc.).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from backtesting.engine import BacktestResult


def generate_report(result: BacktestResult, output_dir: Optional[str] = None) -> dict:
    """
    Génère un rapport complet de backtesting.

    Args:
        result: Résultat du backtesting.
        output_dir: Dossier de sauvegarde (optionnel).

    Returns:
        Dictionnaire avec toutes les métriques.
    """
    report = {
        "meta": {
            "strategy": result.strategy_name,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "start_date": result.start_date.isoformat(),
            "end_date": result.end_date.isoformat(),
            "duration_days": (result.end_date - result.start_date).days,
            "generated_at": datetime.utcnow().isoformat(),
        },
        "capital": {
            "initial": round(result.initial_capital, 2),
            "final": round(result.final_capital, 2),
            "total_return_usd": round(result.final_capital - result.initial_capital, 2),
            "total_return_pct": round(result.total_return_pct, 2),
        },
        "trades": {
            "total": result.total_trades,
            "winning": len(result.winning_trades),
            "losing": len(result.losing_trades),
            "win_rate_pct": round(result.win_rate, 1),
            "avg_win_usd": round(result.avg_win, 4),
            "avg_loss_usd": round(result.avg_loss, 4),
            "profit_factor": round(result.profit_factor, 2),
            "best_trade_usd": round(max((t.pnl for t in result.trades), default=0), 4),
            "worst_trade_usd": round(min((t.pnl for t in result.trades), default=0), 4),
            "avg_duration_bars": round(
                sum(t.duration_bars for t in result.trades) / len(result.trades), 1
            ) if result.trades else 0,
        },
        "risk": {
            "max_drawdown_pct": round(result.max_drawdown_pct, 2),
            "sharpe_ratio": round(result.sharpe_ratio, 3),
            "sortino_ratio": round(_calculate_sortino(result), 3),
            "calmar_ratio": round(_calculate_calmar(result), 3),
        },
        "equity_curve": result.equity_curve[::max(1, len(result.equity_curve) // 200)],  # Max 200 points
    }

    _print_report(report)

    if output_dir:
        _save_report(report, result, output_dir)

    return report


def _calculate_sortino(result: BacktestResult) -> float:
    """Calcule le ratio de Sortino (pénalise uniquement les pertes)."""
    if len(result.trades) < 2:
        return 0.0

    returns = [t.pnl_pct for t in result.trades]
    import statistics
    avg_return = statistics.mean(returns)
    negative_returns = [r for r in returns if r < 0]

    if not negative_returns:
        return float("inf") if avg_return > 0 else 0.0

    downside_std = statistics.stdev(negative_returns) if len(negative_returns) > 1 else abs(negative_returns[0])
    if downside_std == 0:
        return 0.0

    return (avg_return / downside_std) * (252 ** 0.5)


def _calculate_calmar(result: BacktestResult) -> float:
    """Calcule le ratio de Calmar (rendement annuel / drawdown max)."""
    if result.max_drawdown_pct == 0:
        return float("inf") if result.total_return_pct > 0 else 0.0

    days = max((result.end_date - result.start_date).days, 1)
    annual_return = result.total_return_pct * (365 / days)
    return annual_return / result.max_drawdown_pct


def _print_report(report: dict) -> None:
    """Affiche le rapport dans les logs."""
    meta = report["meta"]
    cap = report["capital"]
    trades = report["trades"]
    risk = report["risk"]

    separator = "=" * 60
    logger.info(separator)
    logger.info(f"  RAPPORT DE BACKTESTING — {meta['strategy'].upper()}")
    logger.info(separator)
    logger.info(f"  Symbole     : {meta['symbol']} ({meta['timeframe']})")
    logger.info(f"  Période     : {meta['start_date'][:10]} → {meta['end_date'][:10]} ({meta['duration_days']}j)")
    logger.info("")
    logger.info(f"  Capital initial : ${cap['initial']:,.2f}")
    logger.info(f"  Capital final   : ${cap['final']:,.2f}")
    logger.info(f"  Rendement       : {cap['total_return_pct']:+.2f}% (${cap['total_return_usd']:+,.2f})")
    logger.info("")
    logger.info(f"  Trades total : {trades['total']}")
    logger.info(f"  Win rate     : {trades['win_rate_pct']:.1f}% ({trades['winning']}W / {trades['losing']}L)")
    logger.info(f"  Profit factor: {trades['profit_factor']:.2f}")
    logger.info(f"  Gain moyen   : ${trades['avg_win_usd']:+.4f}")
    logger.info(f"  Perte moyenne: ${trades['avg_loss_usd']:+.4f}")
    logger.info("")
    logger.info(f"  Max Drawdown : {risk['max_drawdown_pct']:.2f}%")
    logger.info(f"  Sharpe Ratio : {risk['sharpe_ratio']:.3f}")
    logger.info(f"  Sortino Ratio: {risk['sortino_ratio']:.3f}")
    logger.info(f"  Calmar Ratio : {risk['calmar_ratio']:.3f}")
    logger.info(separator)


def _save_report(report: dict, result: BacktestResult, output_dir: str) -> None:
    """Sauvegarde le rapport en JSON."""
    try:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        filename = (
            f"backtest_{result.strategy_name}_{result.symbol}_"
            f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        )
        filepath = path / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Rapport sauvegardé: {filepath}")

    except Exception as exc:
        logger.error(f"Erreur sauvegarde rapport: {exc}")
