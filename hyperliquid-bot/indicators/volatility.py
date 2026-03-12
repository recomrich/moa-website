"""
Indicateurs de volatilité — Bollinger Bands, ATR.

Calcule les indicateurs de volatilité pour le dimensionnement
des positions et les niveaux de SL/TP dynamiques.
"""

from typing import Tuple

import pandas as pd
import pandas_ta as ta


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calcule l'Average True Range (ATR).

    Args:
        df: DataFrame OHLCV avec colonnes high, low, close.
        period: Période de calcul (défaut: 14).

    Returns:
        Série ATR.
    """
    result = ta.atr(df["high"], df["low"], df["close"], length=period)
    if result is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return result


def bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    column: str = "close",
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calcule les Bollinger Bands.

    Args:
        df: DataFrame OHLCV.
        period: Période de la moyenne (défaut: 20).
        std_dev: Nombre d'écarts-types (défaut: 2.0).
        column: Colonne source.

    Returns:
        Tuple (upper_band, middle_band, lower_band).
    """
    empty = pd.Series([float("nan")] * len(df), index=df.index)

    result = ta.bbands(df[column], length=period, std=std_dev)
    if result is None or result.empty:
        return empty, empty, empty

    upper_col = f"BBU_{period}_{std_dev}"
    mid_col = f"BBM_{period}_{std_dev}"
    lower_col = f"BBL_{period}_{std_dev}"

    upper = result.get(upper_col, empty)
    middle = result.get(mid_col, empty)
    lower = result.get(lower_col, empty)

    return upper, middle, lower


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Ajoute l'ATR au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        period: Période ATR.

    Returns:
        DataFrame avec colonne atr ajoutée.
    """
    df[f"atr_{period}"] = atr(df, period)
    return df


def add_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    """
    Ajoute les Bollinger Bands au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        period: Période.
        std_dev: Écarts-types.

    Returns:
        DataFrame avec colonnes bb_upper, bb_middle, bb_lower ajoutées.
    """
    upper, middle, lower = bollinger_bands(df, period, std_dev)
    df["bb_upper"] = upper
    df["bb_middle"] = middle
    df["bb_lower"] = lower
    return df


def get_bb_position(
    price: float,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
) -> str:
    """
    Détermine la position du prix par rapport aux Bollinger Bands.

    Args:
        price: Prix courant.
        bb_upper: Bande supérieure.
        bb_middle: Bande médiane.
        bb_lower: Bande inférieure.

    Returns:
        "above_upper", "above_middle", "below_middle", "below_lower".
    """
    import math
    for val in [price, bb_upper, bb_middle, bb_lower]:
        if math.isnan(val):
            return "unknown"

    if price > bb_upper:
        return "above_upper"
    elif price > bb_middle:
        return "above_middle"
    elif price < bb_lower:
        return "below_lower"
    else:
        return "below_middle"


def get_bb_bandwidth(bb_upper: float, bb_middle: float, bb_lower: float) -> float:
    """
    Calcule la largeur des Bollinger Bands (indicateur de volatilité).

    Args:
        bb_upper: Bande supérieure.
        bb_middle: Bande médiane.
        bb_lower: Bande inférieure.

    Returns:
        Bandwidth en pourcentage de la bande médiane.
    """
    import math
    if any(math.isnan(v) for v in [bb_upper, bb_middle, bb_lower]):
        return 0.0
    if bb_middle == 0:
        return 0.0
    return ((bb_upper - bb_lower) / bb_middle) * 100


def get_current_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Retourne la valeur ATR courante (dernière bougie).

    Args:
        df: DataFrame avec colonne ATR pré-calculée.
        period: Période ATR.

    Returns:
        Valeur ATR ou 0.0 si non disponible.
    """
    col = f"atr_{period}"
    if col not in df.columns or df.empty:
        return 0.0

    val = df[col].iloc[-1]
    import math
    return val if not math.isnan(val) else 0.0
