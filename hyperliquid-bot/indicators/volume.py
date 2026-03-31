"""Volume indicators - OBV, Volume SMA."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta


def obv(df: pd.DataFrame) -> pd.Series:
    """Calculate On-Balance Volume."""
    return ta.obv(df["close"], df["volume"])


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate Simple Moving Average of volume."""
    return ta.sma(df["volume"], length=period)


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate volume relative to its moving average."""
    avg = volume_sma(df, period)
    return df["volume"] / avg


def add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all volume indicators to a DataFrame."""
    result = df.copy()

    result["OBV"] = obv(df)
    result["Volume_SMA_20"] = volume_sma(df, 20)
    result["Volume_Ratio"] = volume_ratio(df, 20)

    return result
