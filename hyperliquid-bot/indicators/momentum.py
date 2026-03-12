"""
Indicateurs de momentum — RSI, Stochastique.

Calcule les oscillateurs de momentum pour identifier les zones
de sur-achat et de sur-vente.
"""

from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta


def rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.Series:
    """
    Calcule le RSI (Relative Strength Index).

    Args:
        df: DataFrame OHLCV.
        period: Période de calcul (défaut: 14).
        column: Colonne source.

    Returns:
        Série RSI (0-100).
    """
    result = ta.rsi(df[column], length=period)
    if result is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return result


def stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> Tuple[pd.Series, pd.Series]:
    """
    Calcule l'oscillateur stochastique (%K et %D).

    Args:
        df: DataFrame OHLCV.
        k_period: Période %K (défaut: 14).
        d_period: Période %D (défaut: 3).
        smooth_k: Lissage de %K (défaut: 3).

    Returns:
        Tuple (stoch_k, stoch_d).
    """
    empty = pd.Series([float("nan")] * len(df), index=df.index)

    result = ta.stoch(
        df["high"],
        df["low"],
        df["close"],
        k=k_period,
        d=d_period,
        smooth_k=smooth_k,
    )

    if result is None or result.empty:
        return empty, empty

    k_col = f"STOCHk_{k_period}_{d_period}_{smooth_k}"
    d_col = f"STOCHd_{k_period}_{d_period}_{smooth_k}"

    stoch_k = result.get(k_col, empty)
    stoch_d = result.get(d_col, empty)

    return stoch_k, stoch_d


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Ajoute le RSI au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        period: Période RSI.

    Returns:
        DataFrame avec colonne rsi ajoutée.
    """
    df[f"rsi_{period}"] = rsi(df, period)
    return df


def add_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """
    Ajoute le stochastique au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        k_period: Période %K.
        d_period: Période %D.

    Returns:
        DataFrame avec colonnes stoch_k et stoch_d ajoutées.
    """
    stoch_k, stoch_d = stochastic(df, k_period, d_period)
    df["stoch_k"] = stoch_k
    df["stoch_d"] = stoch_d
    return df


def get_rsi_zone(rsi_value: float, oversold: float = 30, overbought: float = 70) -> str:
    """
    Détermine la zone RSI.

    Args:
        rsi_value: Valeur RSI.
        oversold: Seuil de sur-vente (défaut: 30).
        overbought: Seuil de sur-achat (défaut: 70).

    Returns:
        "oversold", "overbought" ou "neutral".
    """
    if pd.isna(rsi_value):
        return "neutral"
    if rsi_value < oversold:
        return "oversold"
    if rsi_value > overbought:
        return "overbought"
    return "neutral"


def detect_rsi_divergence(
    df: pd.DataFrame,
    rsi_col: str = "rsi_14",
    lookback: int = 20,
) -> Optional[str]:
    """
    Détecte une divergence RSI prix / oscillateur.

    Args:
        df: DataFrame avec RSI pré-calculé.
        rsi_col: Nom de la colonne RSI.
        lookback: Nombre de bougies à analyser.

    Returns:
        "bullish_divergence", "bearish_divergence" ou None.
    """
    if rsi_col not in df.columns or len(df) < lookback:
        return None

    recent = df.tail(lookback)

    price_min_idx = recent["close"].idxmin()
    price_max_idx = recent["close"].idxmax()
    last_idx = recent.index[-1]

    price_low = recent.loc[price_min_idx, "close"]
    price_high = recent.loc[price_max_idx, "close"]
    last_price = recent.iloc[-1]["close"]
    last_rsi = recent.iloc[-1][rsi_col]

    if pd.isna(last_rsi):
        return None

    price_at_low = recent.loc[price_min_idx, rsi_col]
    if (
        last_price < price_low
        and not pd.isna(price_at_low)
        and last_rsi > price_at_low
    ):
        return "bullish_divergence"

    price_at_high = recent.loc[price_max_idx, rsi_col]
    if (
        last_price > price_high
        and not pd.isna(price_at_high)
        and last_rsi < price_at_high
    ):
        return "bearish_divergence"

    return None
