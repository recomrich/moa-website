"""
Indicateurs de tendance — EMA, SMA, MACD.

Calcule les indicateurs de suivi de tendance sur un DataFrame OHLCV
en utilisant pandas-ta pour les calculs optimisés.
"""

from typing import Optional

import pandas as pd
import pandas_ta as ta
from loguru import logger


def ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """
    Calcule la Moyenne Mobile Exponentielle (EMA).

    Args:
        df: DataFrame OHLCV.
        period: Période de calcul.
        column: Colonne source (défaut: "close").

    Returns:
        Série EMA.
    """
    result = ta.ema(df[column], length=period)
    if result is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return result


def sma(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """
    Calcule la Moyenne Mobile Simple (SMA).

    Args:
        df: DataFrame OHLCV.
        period: Période de calcul.
        column: Colonne source.

    Returns:
        Série SMA.
    """
    result = ta.sma(df[column], length=period)
    if result is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return result


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    column: str = "close",
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calcule le MACD (Moving Average Convergence Divergence).

    Args:
        df: DataFrame OHLCV.
        fast: Période rapide (défaut: 12).
        slow: Période lente (défaut: 26).
        signal: Période signal (défaut: 9).
        column: Colonne source.

    Returns:
        Tuple (macd_line, signal_line, histogram).
    """
    empty = pd.Series([float("nan")] * len(df), index=df.index)

    result = ta.macd(df[column], fast=fast, slow=slow, signal=signal)
    if result is None or result.empty:
        return empty, empty, empty

    macd_col = f"MACD_{fast}_{slow}_{signal}"
    signal_col = f"MACDs_{fast}_{slow}_{signal}"
    hist_col = f"MACDh_{fast}_{slow}_{signal}"

    macd_line = result.get(macd_col, empty)
    signal_line = result.get(signal_col, empty)
    histogram = result.get(hist_col, empty)

    return macd_line, signal_line, histogram


def add_ema_indicators(
    df: pd.DataFrame,
    periods: list[int] = None,
) -> pd.DataFrame:
    """
    Ajoute plusieurs EMA au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        periods: Liste de périodes (défaut: [20, 50, 200]).

    Returns:
        DataFrame avec colonnes EMA ajoutées.
    """
    if periods is None:
        periods = [20, 50, 200]

    for period in periods:
        col_name = f"ema_{period}"
        df[col_name] = ema(df, period)

    return df


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    Ajoute les colonnes MACD au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        fast: Période rapide.
        slow: Période lente.
        signal: Période signal.

    Returns:
        DataFrame avec colonnes macd, macd_signal, macd_hist ajoutées.
    """
    macd_line, signal_line, histogram = macd(df, fast, slow, signal)
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram
    return df


def detect_ema_trend(
    df: pd.DataFrame,
    fast_period: int = 20,
    mid_period: int = 50,
    slow_period: int = 200,
) -> Optional[str]:
    """
    Détecte la tendance selon l'alignement des EMA.

    Args:
        df: DataFrame avec colonnes EMA pré-calculées.
        fast_period: Période de l'EMA rapide.
        mid_period: Période de l'EMA médiane.
        slow_period: Période de l'EMA lente.

    Returns:
        "bullish", "bearish" ou "neutral".
    """
    if len(df) < slow_period:
        return "neutral"

    fast_col = f"ema_{fast_period}"
    mid_col = f"ema_{mid_period}"
    slow_col = f"ema_{slow_period}"

    for col in [fast_col, mid_col, slow_col]:
        if col not in df.columns:
            logger.warning(f"Colonne EMA manquante: {col}")
            return "neutral"

    last = df.iloc[-1]

    fast = last.get(fast_col)
    mid = last.get(mid_col)
    slow = last.get(slow_col)

    if any(pd.isna(v) for v in [fast, mid, slow]):
        return "neutral"

    if fast > mid > slow:
        return "bullish"
    elif fast < mid < slow:
        return "bearish"

    return "neutral"


def detect_macd_crossover(df: pd.DataFrame) -> Optional[str]:
    """
    Détecte un croisement MACD.

    Args:
        df: DataFrame avec colonnes macd et macd_signal pré-calculées.

    Returns:
        "bullish_cross" si MACD croise au-dessus du signal,
        "bearish_cross" si MACD croise en-dessous,
        None si pas de croisement.
    """
    if len(df) < 2 or "macd" not in df.columns or "macd_signal" not in df.columns:
        return None

    current = df.iloc[-1]
    previous = df.iloc[-2]

    curr_macd = current["macd"]
    curr_signal = current["macd_signal"]
    prev_macd = previous["macd"]
    prev_signal = previous["macd_signal"]

    if any(pd.isna(v) for v in [curr_macd, curr_signal, prev_macd, prev_signal]):
        return None

    if prev_macd <= prev_signal and curr_macd > curr_signal:
        return "bullish_cross"
    elif prev_macd >= prev_signal and curr_macd < curr_signal:
        return "bearish_cross"

    return None
