"""
================================================================================
CHI BAO: WPR(14) + EMA(5), ATR(14)
================================================================================
Cong thuc GIONG HET ban backtest (final_trading_system.py) de dam bao tin hieu
live khop voi tin hieu da kiem chung.
================================================================================
"""
import pandas as pd
import numpy as np
from config import WPR_PERIOD, EMA_SPAN, ATR_PERIOD, VN_OFFSET_HOURS


def wpr_ema(high, low, close, period=WPR_PERIOD, span=EMA_SPAN):
    highest = pd.Series(high).rolling(period).max().values
    lowest = pd.Series(low).rolling(period).min().values
    raw = -100 * (highest - close) / (highest - lowest)
    return pd.Series(raw).ewm(span=span, adjust=False).mean().values


def atr_calc(high, low, close, period=ATR_PERIOD):
    prev = np.roll(close, 1); prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    a = np.full(len(close), np.nan)
    a[period - 1] = tr[:period].mean()
    for i in range(period, len(close)):
        a[i] = (a[i - 1] * (period - 1) + tr[i]) / period
    return a


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Them cot wpr, atr, Time_VN, Hour_VN, Date_VN vao df co san Time/Open/High/Low/Close (UTC)."""
    df = df.copy()
    df["wpr"] = wpr_ema(df["High"].values, df["Low"].values, df["Close"].values)
    df["atr"] = atr_calc(df["High"].values, df["Low"].values, df["Close"].values)
    df["Time_VN"] = df["Time"] + pd.Timedelta(hours=VN_OFFSET_HOURS)
    df["Hour_VN"] = df["Time_VN"].dt.hour
    df["Date_VN"] = df["Time_VN"].dt.date
    return df
