"""
All 20 candlestick patterns.

Single candle  : Doji, Hammer, Inverted Hammer, Hanging Man, Shooting Star,
                 Spinning Top, Marubozu (bull/bear)
Two candle     : Bullish/Bearish Engulfing, Bullish/Bearish Harami,
                 Piercing Line, Dark Cloud Cover, Tweezer Bottom/Top
Three candle   : Morning Star, Evening Star, Three White Soldiers,
                 Three Black Crows, Three Inside Up/Down

Each detector returns a boolean Series over the full DataFrame.
Call apply_all_patterns(df) to add all pattern columns at once.
"""

import numpy as np
import pandas as pd


# ── Helpers ───────────────────────────────────────────────────────────────────

def _metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["body"]        = (df["close"] - df["open"]).abs()
    df["range"]       = (df["high"] - df["low"]).replace(0, np.nan)
    df["upper_wick"]  = df["high"] - df[["open","close"]].max(axis=1)
    df["lower_wick"]  = df[["open","close"]].min(axis=1) - df["low"]
    df["is_bull"]     = df["close"] > df["open"]
    df["is_bear"]     = df["close"] < df["open"]
    df["body_pct"]    = df["body"] / df["range"]
    df["mid_body"]    = (df["open"] + df["close"]) / 2
    return df


# ── Single candle patterns ─────────────────────────────────────────────────────

def doji(df, body_pct=0.1):
    """Body < 10% of range → indecision."""
    return df["body_pct"] < body_pct


def spinning_top(df, body_lo=0.1, body_hi=0.3):
    """Body between 10-30% of range, wicks on both sides → indecision."""
    eq_wicks = (df["upper_wick"] > 0) & (df["lower_wick"] > 0)
    return eq_wicks & df["body_pct"].between(body_lo, body_hi)


def hammer(df, wick_ratio=2.0, upper_max=0.3):
    """Long lower wick, small body near top. Bullish reversal."""
    return (
        df["is_bull"]
        & (df["lower_wick"] >= wick_ratio * df["body"])
        & (df["upper_wick"] <= upper_max * df["body"].replace(0, np.nan))
        & (df["body"] > 0)
    ).fillna(False)


def inverted_hammer(df, wick_ratio=2.0, lower_max=0.3):
    """Long upper wick, small body near bottom. Bullish reversal after downtrend."""
    return (
        df["is_bull"]
        & (df["upper_wick"] >= wick_ratio * df["body"])
        & (df["lower_wick"] <= lower_max * df["body"].replace(0, np.nan))
        & (df["body"] > 0)
    ).fillna(False)


def hanging_man(df, wick_ratio=2.0, upper_max=0.3):
    """Looks like hammer but bearish candle → bearish reversal after uptrend."""
    return (
        df["is_bear"]
        & (df["lower_wick"] >= wick_ratio * df["body"])
        & (df["upper_wick"] <= upper_max * df["body"].replace(0, np.nan))
        & (df["body"] > 0)
    ).fillna(False)


def shooting_star(df, wick_ratio=2.0, lower_max=0.3):
    """Long upper wick, small body near bottom. Bearish reversal."""
    return (
        df["is_bear"]
        & (df["upper_wick"] >= wick_ratio * df["body"])
        & (df["lower_wick"] <= lower_max * df["body"].replace(0, np.nan))
        & (df["body"] > 0)
    ).fillna(False)


def marubozu_bull(df, wick_max=0.05):
    """Almost no wicks, full green body → strong buying momentum."""
    return (
        df["is_bull"]
        & (df["upper_wick"] / df["range"] < wick_max)
        & (df["lower_wick"] / df["range"] < wick_max)
    ).fillna(False)


def marubozu_bear(df, wick_max=0.05):
    """Almost no wicks, full red body → strong selling momentum."""
    return (
        df["is_bear"]
        & (df["upper_wick"] / df["range"] < wick_max)
        & (df["lower_wick"] / df["range"] < wick_max)
    ).fillna(False)


# ── Two candle patterns ────────────────────────────────────────────────────────

def bullish_engulfing(df):
    p_bear  = df["is_bear"].shift(1)
    p_open  = df["open"].shift(1)
    p_close = df["close"].shift(1)
    return (p_bear & df["is_bull"] & (df["close"] > p_open) & (df["open"] < p_close)).fillna(False)


def bearish_engulfing(df):
    p_bull  = df["is_bull"].shift(1)
    p_open  = df["open"].shift(1)
    p_close = df["close"].shift(1)
    return (p_bull & df["is_bear"] & (df["open"] > p_close) & (df["close"] < p_open)).fillna(False)


def bullish_harami(df):
    """Small green candle fits INSIDE previous big red candle → reversal."""
    p_bear  = df["is_bear"].shift(1)
    p_open  = df["open"].shift(1)
    p_close = df["close"].shift(1)
    inside  = (df["open"] > p_close) & (df["close"] < p_open)
    return (p_bear & df["is_bull"] & inside).fillna(False)


def bearish_harami(df):
    """Small red candle fits inside previous big green candle → reversal."""
    p_bull  = df["is_bull"].shift(1)
    p_open  = df["open"].shift(1)
    p_close = df["close"].shift(1)
    inside  = (df["open"] < p_close) & (df["close"] > p_open)
    return (p_bull & df["is_bear"] & inside).fillna(False)


def piercing_line(df):
    """Red candle followed by green that closes above midpoint of red → bullish reversal."""
    p_bear   = df["is_bear"].shift(1)
    p_mid    = df["mid_body"].shift(1)
    p_open   = df["open"].shift(1)
    gap_down = df["open"] < df["close"].shift(1)
    return (p_bear & df["is_bull"] & gap_down & (df["close"] > p_mid) & (df["close"] < p_open)).fillna(False)


def dark_cloud_cover(df):
    """Green candle followed by red that closes below midpoint of green → bearish reversal."""
    p_bull   = df["is_bull"].shift(1)
    p_mid    = df["mid_body"].shift(1)
    p_open   = df["open"].shift(1)
    gap_up   = df["open"] > df["close"].shift(1)
    return (p_bull & df["is_bear"] & gap_up & (df["close"] < p_mid) & (df["close"] > p_open)).fillna(False)


def tweezer_bottom(df, tolerance=0.001):
    """Two candles with same low → strong support level."""
    same_low = (df["low"] - df["low"].shift(1)).abs() / df["low"].shift(1) <= tolerance
    return (df["is_bear"].shift(1) & df["is_bull"] & same_low).fillna(False)


def tweezer_top(df, tolerance=0.001):
    """Two candles with same high → strong resistance level."""
    same_high = (df["high"] - df["high"].shift(1)).abs() / df["high"].shift(1) <= tolerance
    return (df["is_bull"].shift(1) & df["is_bear"] & same_high).fillna(False)


# ── Three candle patterns ──────────────────────────────────────────────────────

def morning_star(df, doji_body=0.1):
    """
    Big red → small/doji → big green closing above red midpoint.
    Strong bullish reversal. Most reliable 3-candle pattern.
    """
    c1_bear = df["is_bear"].shift(2)
    c1_big  = df["body_pct"].shift(2) > 0.5
    c2_small= df["body_pct"].shift(1) < doji_body
    c3_bull = df["is_bull"]
    c3_above= df["close"] > df["mid_body"].shift(2)
    return (c1_bear & c1_big & c2_small & c3_bull & c3_above).fillna(False)


def evening_star(df, doji_body=0.1):
    """
    Big green → small/doji → big red closing below green midpoint.
    Strong bearish reversal.
    """
    c1_bull = df["is_bull"].shift(2)
    c1_big  = df["body_pct"].shift(2) > 0.5
    c2_small= df["body_pct"].shift(1) < doji_body
    c3_bear = df["is_bear"]
    c3_below= df["close"] < df["mid_body"].shift(2)
    return (c1_bull & c1_big & c2_small & c3_bear & c3_below).fillna(False)


def three_white_soldiers(df, min_body_pct=0.5):
    """Three consecutive strong green candles → powerful bullish continuation."""
    b1 = df["is_bull"].shift(2) & (df["body_pct"].shift(2) > min_body_pct)
    b2 = df["is_bull"].shift(1) & (df["body_pct"].shift(1) > min_body_pct) & (df["close"].shift(1) > df["close"].shift(2))
    b3 = df["is_bull"] & (df["body_pct"] > min_body_pct) & (df["close"] > df["close"].shift(1))
    return (b1 & b2 & b3).fillna(False)


def three_black_crows(df, min_body_pct=0.5):
    """Three consecutive strong red candles → powerful bearish continuation."""
    b1 = df["is_bear"].shift(2) & (df["body_pct"].shift(2) > min_body_pct)
    b2 = df["is_bear"].shift(1) & (df["body_pct"].shift(1) > min_body_pct) & (df["close"].shift(1) < df["close"].shift(2))
    b3 = df["is_bear"] & (df["body_pct"] > min_body_pct) & (df["close"] < df["close"].shift(1))
    return (b1 & b2 & b3).fillna(False)


def three_inside_up(df):
    """Bullish harami + confirming green candle → bullish reversal."""
    harami = bullish_harami(df).shift(1)
    confirm= df["is_bull"] & (df["close"] > df["close"].shift(1))
    return (harami & confirm).fillna(False)


def three_inside_down(df):
    """Bearish harami + confirming red candle → bearish reversal."""
    harami = bearish_harami(df).shift(1)
    confirm= df["is_bear"] & (df["close"] < df["close"].shift(1))
    return (harami & confirm).fillna(False)


# ── Apply all ─────────────────────────────────────────────────────────────────

def apply_all_patterns(df: pd.DataFrame) -> pd.DataFrame:
    df = _metrics(df)
    # single
    df["pat_doji"]             = doji(df)
    df["pat_spinning_top"]     = spinning_top(df)
    df["pat_hammer"]           = hammer(df)
    df["pat_inv_hammer"]       = inverted_hammer(df)
    df["pat_hanging_man"]      = hanging_man(df)
    df["pat_shooting_star"]    = shooting_star(df)
    df["pat_marubozu_bull"]    = marubozu_bull(df)
    df["pat_marubozu_bear"]    = marubozu_bear(df)
    # two candle
    df["pat_bull_engulf"]      = bullish_engulfing(df)
    df["pat_bear_engulf"]      = bearish_engulfing(df)
    df["pat_bull_harami"]      = bullish_harami(df)
    df["pat_bear_harami"]      = bearish_harami(df)
    df["pat_piercing"]         = piercing_line(df)
    df["pat_dark_cloud"]       = dark_cloud_cover(df)
    df["pat_tweezer_bot"]      = tweezer_bottom(df)
    df["pat_tweezer_top"]      = tweezer_top(df)
    # three candle
    df["pat_morning_star"]     = morning_star(df)
    df["pat_evening_star"]     = evening_star(df)
    df["pat_3_soldiers"]       = three_white_soldiers(df)
    df["pat_3_crows"]          = three_black_crows(df)
    df["pat_3_inside_up"]      = three_inside_up(df)
    df["pat_3_inside_down"]    = three_inside_down(df)
    return df


# ── Pattern strength classification ───────────────────────────────────────────

HIGH_CONF_BULL = ["pat_morning_star", "pat_3_soldiers", "pat_bull_engulf", "pat_3_inside_up"]
HIGH_CONF_BEAR = ["pat_evening_star", "pat_3_crows",    "pat_bear_engulf", "pat_3_inside_down"]
MED_CONF_BULL  = ["pat_hammer", "pat_inv_hammer", "pat_piercing", "pat_tweezer_bot", "pat_bull_harami"]
MED_CONF_BEAR  = ["pat_shooting_star", "pat_hanging_man", "pat_dark_cloud", "pat_tweezer_top", "pat_bear_harami"]
LOW_CONF       = ["pat_doji", "pat_spinning_top", "pat_marubozu_bull", "pat_marubozu_bear"]


def get_pattern_signal(row) -> tuple:
    # Phase 1 — Blocked patterns (confirmed losers from real trading data)
    # Piercing: 0W 5L across all days = -Rs.4,572
    # Dark Cloud: 1W 5L across all days = -Rs.5,401
    # Bull Harami: 4W 13L across all days = -Rs.4,270
    # 3 Crows: 0W 3L across all days = -Rs.2,874
    # 3 Soldiers: 1W 2L across all days = -Rs.2,612
    BLOCKED = [
        "pat_piercing",
        "pat_dark_cloud",
        "pat_bull_harami",
        "pat_3_crows",
        "pat_3_soldiers",
    ]
    for col in BLOCKED:
        if row.get(col):
            return None, ""
    for col in HIGH_CONF_BULL:
        if row.get(col): return "BUY", "HIGH"
    for col in HIGH_CONF_BEAR:
        if row.get(col): return "SELL", "HIGH"
    for col in MED_CONF_BULL:
        if row.get(col): return "BUY", "MEDIUM"
    for col in MED_CONF_BEAR:
        if row.get(col): return "SELL", "MEDIUM"
    return None, ""
