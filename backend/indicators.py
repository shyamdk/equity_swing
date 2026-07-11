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

    try:
        # RSI(14)
        df["rsi"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

        # CCI(20)
        df["cci"] = ta.trend.CCIIndicator(high=high, low=low, close=close, window=20).cci()

        # MACD(12, 26, 9)
        macd_ind = ta.trend.MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
        df["macd"] = macd_ind.macd()
        df["macd_signal"] = macd_ind.macd_signal()
        df["macd_hist"] = macd_ind.macd_diff()

        # Bollinger Bands(20, 2)
        bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()

        # EMA(20), EMA(50), EMA(200)
        df["ema_20"] = ta.trend.EMAIndicator(close=close, window=20).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(close=close, window=50).ema_indicator()
        df["ema_200"] = ta.trend.EMAIndicator(close=close, window=200).ema_indicator()

        # ATR(14)
        df["atr"] = ta.volatility.AverageTrueRange(
            high=high, low=low, close=close, window=14
        ).average_true_range()

        # VWAP — meaningful only for intraday; reset each calendar day
        if is_intraday and "timestamp" in df.columns:
            df["vwap"] = _vwap_daily(df)
        else:
            df["vwap"] = None

    except Exception as e:
        logger.warning(f"Indicator calculation error: {e}")

    return df


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
