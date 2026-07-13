"""
Technical indicators used as confirmation filters on top of candlestick patterns.
RSI, VWAP, EMA (fast/slow), ADX (trend strength), ATR, Volume surge.
All functions take a DataFrame and return it with new indicator columns added.
"""

import numpy as np
import pandas as pd
from config import Config


def add_rsi(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
    period = period or Config.RSI_PERIOD
    delta  = df["close"].diff()
    gain   = delta.clip(lower=0).rolling(period).mean()
    loss   = (-delta.clip(upper=0)).rolling(period).mean()
    rs     = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_ema(df: pd.DataFrame, fast: int = None, slow: int = None) -> pd.DataFrame:
    fast = fast or Config.EMA_FAST
    slow = slow or Config.EMA_SLOW
    df[f"ema_{fast}"] = df["close"].ewm(span=fast, adjust=False).mean()
    df[f"ema_{slow}"] = df["close"].ewm(span=slow, adjust=False).mean()
    df["ema_bull"]    = df[f"ema_{fast}"] > df[f"ema_{slow}"]  # fast above slow = bullish
    df["ema_bear"]    = df[f"ema_{fast}"] < df[f"ema_{slow}"]
    return df


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    VWAP resets at start of each trading day.
    Groups by date, computes cumulative (price * volume) / cumulative volume.
    """
    if "timestamp" not in df.columns:
        df["vwap"] = np.nan
        return df
    df = df.copy()
    df["date"]      = df["timestamp"].dt.date
    df["tp"]        = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"]    = df["tp"] * df["volume"]
    df["cum_tp_vol"]= df.groupby("date")["tp_vol"].cumsum()
    df["cum_vol"]   = df.groupby("date")["volume"].cumsum()
    df["vwap"]      = df["cum_tp_vol"] / df["cum_vol"].replace(0, np.nan)
    df["above_vwap"]= df["close"] > df["vwap"]
    df["below_vwap"]= df["close"] < df["vwap"]
    df.drop(columns=["date","tp","tp_vol","cum_tp_vol","cum_vol"], inplace=True)
    return df


def add_atr(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
    period = period or Config.ATR_PERIOD
    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift(1)).abs()
    lpc = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=period, adjust=False).mean()
    return df


def add_adx(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
    """
    ADX measures trend strength (not direction).
    ADX > 20 = trending market (good for our strategy).
    ADX < 20 = sideways/choppy (avoid trading).
    """
    period = period or Config.ADX_PERIOD
    high, low, close = df["high"], df["low"], df["close"]

    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    tr = pd.concat([high - low,
                    (high - close.shift()).abs(),
                    (low  - close.shift()).abs()], axis=1).max(axis=1)

    atr_s     = tr.ewm(span=period, adjust=False).mean()
    plus_di   = 100 * pd.Series(plus_dm, index=df.index).ewm(span=period, adjust=False).mean() / atr_s
    minus_di  = 100 * pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean() / atr_s
    dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)

    df["adx"]       = dx.ewm(span=period, adjust=False).mean()
    df["is_trending"]= df["adx"] > Config.ADX_TREND_THRESHOLD
    return df


def add_volume_surge(df: pd.DataFrame, lookback: int = 20, mult: float = None) -> pd.DataFrame:
    mult = mult or Config.VOLUME_SURGE_MULT
    df["vol_avg"]   = df["volume"].rolling(lookback).mean()
    df["vol_surge"] = df["volume"] >= (df["vol_avg"] * mult)
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add every indicator to the dataframe in one call."""
    df = add_rsi(df)
    df = add_ema(df)
    df = add_vwap(df)
    df = add_atr(df)
    df = add_adx(df)
    df = add_volume_surge(df)
    return df
