"""Trend indicators - EMA, SMA, MACD."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta


def ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """Calculate Exponential Moving Average."""
    return ta.ema(df[column], length=period)


def sma(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """Calculate Simple Moving Average."""
    return ta.sma(df[column], length=period)


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    column: str = "close",
) -> pd.DataFrame:
    """Calculate MACD (Moving Average Convergence Divergence).

    Returns DataFrame with columns: MACD, Signal, Histogram.
    """
    result = ta.macd(df[column], fast=fast, slow=slow, signal=signal)
    if result is None:
        return pd.DataFrame(
            {"MACD": [], "Signal": [], "Histogram": []}, index=df.index
        )

    result.columns = ["MACD", "Histogram", "Signal"]
    return result


def add_trend_indicators(
    df: pd.DataFrame, ema_periods: list[int] | None = None
) -> pd.DataFrame:
    """Add all trend indicators to a DataFrame."""
    if ema_periods is None:
        ema_periods = [20, 50, 200]

    result = df.copy()

    for period in ema_periods:
        result[f"EMA_{period}"] = ema(df, period)

    macd_data = macd(df)
    result["MACD"] = macd_data["MACD"]
    result["MACD_Signal"] = macd_data["Signal"]
    result["MACD_Histogram"] = macd_data["Histogram"]

    return result
