"""
Indicateurs de volume — Volume moyen, OBV, confirmation de volume.

Calcule les indicateurs basés sur le volume pour la confirmation
des signaux et la détection des breakouts.
"""

import pandas as pd
import pandas_ta as ta


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calcule la moyenne mobile simple du volume.

    Args:
        df: DataFrame OHLCV avec colonne volume.
        period: Période de calcul.

    Returns:
        Série volume SMA.
    """
    result = ta.sma(df["volume"], length=period)
    if result is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return result


def obv(df: pd.DataFrame) -> pd.Series:
    """
    Calcule l'On-Balance Volume (OBV).

    Args:
        df: DataFrame OHLCV.

    Returns:
        Série OBV.
    """
    result = ta.obv(df["close"], df["volume"])
    if result is None:
        return pd.Series([float("nan")] * len(df), index=df.index)
    return result


def add_volume_indicators(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Ajoute les indicateurs de volume au DataFrame.

    Args:
        df: DataFrame OHLCV (modifié in-place).
        period: Période pour la moyenne de volume.

    Returns:
        DataFrame avec colonnes volume_sma et obv ajoutées.
    """
    df[f"volume_sma_{period}"] = volume_sma(df, period)
    df["obv"] = obv(df)
    return df


def is_high_volume(
    df: pd.DataFrame,
    multiplier: float = 1.5,
    period: int = 20,
) -> bool:
    """
    Vérifie si le volume actuel est supérieur à la moyenne × multiplicateur.

    Args:
        df: DataFrame avec volume_sma pré-calculée.
        multiplier: Facteur de multiplication (défaut: 1.5).
        period: Période de la SMA volume.

    Returns:
        True si le volume actuel est élevé.
    """
    if df.empty:
        return False

    col = f"volume_sma_{period}"
    if col not in df.columns:
        return False

    last = df.iloc[-1]
    current_volume = last.get("volume")
    avg_volume = last.get(col)

    import math
    if (
        current_volume is None
        or avg_volume is None
        or math.isnan(current_volume)
        or math.isnan(avg_volume)
        or avg_volume == 0
    ):
        return False

    return current_volume >= (avg_volume * multiplier)


def get_volume_ratio(df: pd.DataFrame, period: int = 20) -> float:
    """
    Calcule le ratio volume actuel / volume moyen.

    Args:
        df: DataFrame OHLCV.
        period: Période pour la moyenne.

    Returns:
        Ratio volume (1.0 = volume moyen).
    """
    if df.empty:
        return 1.0

    col = f"volume_sma_{period}"
    if col not in df.columns:
        vol_sma = volume_sma(df, period)
        avg = vol_sma.iloc[-1] if not vol_sma.empty else None
    else:
        avg = df.iloc[-1].get(col)

    current = df.iloc[-1].get("volume")

    import math
    if (
        current is None
        or avg is None
        or math.isnan(float(current))
        or math.isnan(float(avg))
        or float(avg) == 0
    ):
        return 1.0

    return float(current) / float(avg)


def detect_volume_climax(df: pd.DataFrame, period: int = 20, threshold: float = 3.0) -> bool:
    """
    Détecte un climax de volume (volume extrêmement élevé).

    Peut signaler un retournement potentiel ou une cassure majeure.

    Args:
        df: DataFrame OHLCV.
        period: Période de référence.
        threshold: Multiplicateur pour considérer comme climax.

    Returns:
        True si climax de volume détecté.
    """
    return get_volume_ratio(df, period) >= threshold
