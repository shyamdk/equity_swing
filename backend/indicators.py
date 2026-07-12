"""Technical indicator calculation using the `ta` library."""
import pandas as pd
import ta
from loguru import logger


def calculate_indicators(df: pd.DataFrame, is_intraday: bool = True) -> pd.DataFrame:
    """
    Add technical indicator columns to an OHLCV DataFrame.

    Expected input columns: open, high, low, close, volume
    Added columns: rsi, cci, macd, macd_signal, macd_hist,
                   bb_upper, bb_middle, bb_lower,
                   ema_20, ema_50, ema_200, atr, vwap (intraday only)

    Returns the DataFrame with indicator columns added (NaN where insufficient data).
    """
    if df.empty:
        return df

    df = df.copy()

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # Each indicator is computed independently: on a short series `ta` can raise, and
    # a single shared try/except would silently blank *every* other indicator too.
    def _safe(name: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            logger.debug(f"Indicator '{name}' skipped ({len(df)} rows): {e}")
            for col in _COLUMNS_OF[name]:
                if col not in df.columns:
                    df[col] = None

    _safe("rsi", lambda: df.__setitem__(
        "rsi", ta.momentum.RSIIndicator(close=close, window=14).rsi()))

    _safe("cci", lambda: df.__setitem__(
        "cci", ta.trend.CCIIndicator(high=high, low=low, close=close, window=20).cci()))

    def _macd() -> None:
        m = ta.trend.MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
        df["macd"], df["macd_signal"], df["macd_hist"] = m.macd(), m.macd_signal(), m.macd_diff()
    _safe("macd", _macd)

    def _bb() -> None:
        bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()
    _safe("bb", _bb)

    for window in (20, 50, 200):
        _safe(f"ema_{window}", (lambda w: lambda: df.__setitem__(
            f"ema_{w}", ta.trend.EMAIndicator(close=close, window=w).ema_indicator()))(window))

    _safe("atr", lambda: df.__setitem__("atr", ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14).average_true_range()))

    # VWAP — meaningful only for intraday; reset each calendar day
    if is_intraday and "timestamp" in df.columns:
        _safe("vwap", lambda: df.__setitem__("vwap", _vwap_daily(df)))
    else:
        df["vwap"] = None

    return df


# Columns each indicator is responsible for (used to NULL-fill on failure).
_COLUMNS_OF: dict[str, list[str]] = {
    "rsi": ["rsi"],
    "cci": ["cci"],
    "macd": ["macd", "macd_signal", "macd_hist"],
    "bb": ["bb_upper", "bb_middle", "bb_lower"],
    "ema_20": ["ema_20"], "ema_50": ["ema_50"], "ema_200": ["ema_200"],
    "atr": ["atr"],
    "vwap": ["vwap"],
}


def _vwap_daily(df: pd.DataFrame) -> pd.Series:
    """
    Cumulative VWAP, reset at the start of each trading day.
    Typical price = (high + low + close) / 3.
    """
    df = df.copy()
    df["_date"] = pd.to_datetime(df["timestamp"]).dt.date
    df["_tp"] = (df["high"] + df["low"] + df["close"]) / 3
    df["_tp_vol"] = df["_tp"] * df["volume"]

    vwap = (
        df.groupby("_date")["_tp_vol"].cumsum()
        / df.groupby("_date")["volume"].cumsum()
    )
    return vwap
