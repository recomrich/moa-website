"""Momentum indicators - RSI, Stochastic."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta


def rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.Series:
    """Calculate Relative Strength Index."""
    return ta.rsi(df[column], length=period)


def stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> pd.DataFrame:
    """Calculate Stochastic Oscillator.

    Returns DataFrame with columns: %K, %D.
    """
    result = ta.stoch(
        df["high"], df["low"], df["close"],
        k=k_period, d=d_period, smooth_k=smooth_k
    )
    if result is None:
        return pd.DataFrame({"%K": [], "%D": []}, index=df.index)

    result.columns = ["%K", "%D"]
    return result


def add_momentum_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all momentum indicators to a DataFrame."""
    result = df.copy()

    result["RSI"] = rsi(df)

    stoch_data = stochastic(df)
    result["Stoch_K"] = stoch_data["%K"]
    result["Stoch_D"] = stoch_data["%D"]

    return result
