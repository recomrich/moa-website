"""Volatility indicators - Bollinger Bands, ATR."""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta


def bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    column: str = "close",
) -> pd.DataFrame:
    """Calculate Bollinger Bands.

    Returns DataFrame with columns: BB_Upper, BB_Middle, BB_Lower.
    """
    result = ta.bbands(df[column], length=period, std=std_dev)
    if result is None:
        return pd.DataFrame(
            {"BB_Lower": [], "BB_Middle": [], "BB_Upper": []},
            index=df.index,
        )

    result.columns = ["BB_Lower", "BB_Middle", "BB_Upper", "BB_Bandwidth", "BB_Percent"]
    return result[["BB_Upper", "BB_Middle", "BB_Lower"]]


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    return ta.atr(df["high"], df["low"], df["close"], length=period)


def add_volatility_indicators(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> pd.DataFrame:
    """Add all volatility indicators to a DataFrame."""
    result = df.copy()

    bb_data = bollinger_bands(df, bb_period, bb_std)
    result["BB_Upper"] = bb_data["BB_Upper"]
    result["BB_Middle"] = bb_data["BB_Middle"]
    result["BB_Lower"] = bb_data["BB_Lower"]

    result["ATR"] = atr(df)

    return result
