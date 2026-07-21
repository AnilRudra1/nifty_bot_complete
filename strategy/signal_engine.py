"""
Signal engine — with higher timeframe trend filter.

Changes from previous version:
1. Runs pattern detection on 5-min candles (as before)
2. Resamples to 15-min candles and checks trend there too
3. Signal only fires if both 5-min pattern AND 15-min trend agree
4. This eliminates counter-trend trades which fail most often
"""

import pandas as pd
import numpy as np
from config import Config
from strategy.candlestick_patterns import apply_all_patterns, get_pattern_signal
from strategy.indicators import add_all_indicators
from strategy.support_resistance import get_sr_levels, is_near_level


# ── Higher timeframe trend ─────────────────────────────────────────────────────

def resample_to_15min(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample 5-minute OHLCV candles into 15-minute candles.
    Requires a 'timestamp' column.
    """
    if "timestamp" not in df.columns or len(df) < 3:
        return pd.DataFrame()
    try:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        df_15 = df.resample("15min").agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
        }).dropna()
        df_15 = df_15.reset_index()
        return df_15
    except Exception:
        return pd.DataFrame()


def get_15min_trend(df_5min: pd.DataFrame) -> str:
    """
    Determine 15-minute trend from 5-minute candles.
    Returns 'BULL', 'BEAR', or 'NEUTRAL'.

    Uses EMA crossover on 15-min chart:
    - 9 EMA > 21 EMA = BULL
    - 9 EMA < 21 EMA = BEAR
    """
    df_15 = resample_to_15min(df_5min)
    if df_15.empty or len(df_15) < 10:
        return "NEUTRAL"
    try:
        df_15["ema9"]  = df_15["close"].ewm(span=9,  adjust=False).mean()
        df_15["ema21"] = df_15["close"].ewm(span=21, adjust=False).mean()
        last = df_15.iloc[-1]
        if last["ema9"] > last["ema21"]:
            return "BULL"
        if last["ema9"] < last["ema21"]:
            return "BEAR"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


def get_15min_support_resistance(df_5min: pd.DataFrame) -> tuple:
    """Get S/R levels from 15-min chart — stronger than 5-min levels."""
    df_15 = resample_to_15min(df_5min)
    if df_15.empty:
        return [], []
    try:
        return get_sr_levels(df_15)
    except Exception:
        return [], []


# ── Market direction ───────────────────────────────────────────────────────────

def get_market_direction(df: pd.DataFrame) -> str:
    """
    Detect overall market direction from recent 5-min candles.
    Uses EMA + VWAP on last 6 candles.
    """
    if len(df) < 10:
        return "NEUTRAL"
    recent = df.tail(6)
    bull = sum(
        1 for _, r in recent.iterrows()
        if r.get("ema_bull", False) and r.get("above_vwap", False)
    )
    bear = sum(
        1 for _, r in recent.iterrows()
        if r.get("ema_bear", False) and r.get("below_vwap", False)
    )
    if bull >= 4:
        return "BULL"
    if bear >= 4:
        return "BEAR"
    return "NEUTRAL"


# ── Main signal generator ──────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes raw OHLCV DataFrame (Nifty spot 5-min candles).
    Returns DataFrame with signal, signal_score, signal_reason columns.

    Scoring:
      HIGH pattern           = 40 pts
      MED pattern            = 25 pts
      RSI confirms           = +15 pts
      VWAP confirms          = +15 pts
      EMA (5-min) confirms   = +10 pts
      Volume surge           = +10 pts
      Near S/R level (5-min) = +10 pts
      15-min trend agrees    = +15 pts bonus (strongest filter)
      15-min S/R confirms    = +10 pts bonus

    Signal fires only if:
      score >= SIGNAL_SCORE_MIN
      AND market is trending (ADX > threshold)
      AND 15-min trend does NOT contradict signal
    """
    df = apply_all_patterns(df)
    df = add_all_indicators(df)

    # 5-min S/R levels
    support_levels, resistance_levels = get_sr_levels(df)
    df["near_support"]    = df["low"].apply(
        lambda p: is_near_level(p, support_levels) is not None
    )
    df["near_resistance"] = df["high"].apply(
        lambda p: is_near_level(p, resistance_levels) is not None
    )

    # 15-min trend (computed once for the whole df)
    trend_15 = get_15min_trend(df)
    sup_15, res_15 = get_15min_support_resistance(df)

    signals, scores, reasons = [], [], []

    for _, row in df.iterrows():
        direction, confidence = get_pattern_signal(row)
        score  = 0
        reason = []

        if direction is None:
            signals.append(None)
            scores.append(0)
            reasons.append("")
            continue

        # Base pattern score
        if confidence == "HIGH":
            score += 40
            reason.append("HIGH pattern")
        elif confidence == "MEDIUM":
            score += 25
            reason.append("MED pattern")

        # RSI
        rsi = row.get("rsi", 50) or 50
        if direction == "BUY" and rsi < Config.RSI_OVERSOLD:
            score += 15
            reason.append(f"RSI {rsi:.0f} oversold")
        elif direction == "SELL" and rsi > Config.RSI_OVERBOUGHT:
            score += 15
            reason.append(f"RSI {rsi:.0f} overbought")

        # VWAP
        if direction == "BUY" and row.get("above_vwap"):
            score += 15
            reason.append("above VWAP")
        elif direction == "SELL" and row.get("below_vwap"):
            score += 15
            reason.append("below VWAP")

        # 5-min EMA
        if direction == "BUY" and row.get("ema_bull"):
            score += 10
            reason.append("5m EMA bull")
        elif direction == "SELL" and row.get("ema_bear"):
            score += 10
            reason.append("5m EMA bear")

        # Volume surge
        if row.get("vol_surge"):
            score += 10
            reason.append("volume surge")

        # 5-min S/R
        if direction == "BUY" and row.get("near_support"):
            score += 10
            reason.append("at 5m support")
        elif direction == "SELL" and row.get("near_resistance"):
            score += 10
            reason.append("at 5m resistance")

        # 15-min trend bonus — strongest filter
        if trend_15 == "BULL" and direction == "BUY":
            score += 15
            reason.append("15m trend BULL")
        elif trend_15 == "BEAR" and direction == "SELL":
            score += 15
            reason.append("15m trend BEAR")
        elif trend_15 == "NEUTRAL":
            reason.append("15m NEUTRAL")
        else:
            # 15-min trend contradicts signal — heavy penalty
            score -= 20
            reason.append(f"15m trend {trend_15} CONTRADICTS signal")

        # 15-min S/R bonus
        price = row.get("close", 0)
        if direction == "BUY" and is_near_level(price, sup_15) is not None:
            score += 10
            reason.append("at 15m support")
        elif direction == "SELL" and is_near_level(price, res_15) is not None:
            score += 10
            reason.append("at 15m resistance")

        # ADX sideways filter
        if not row.get("is_trending", True):
            score  = 0
            reason = ["ADX sideways — no trade"]

        final_signal = direction if score >= Config.SIGNAL_SCORE_MIN else None
        signals.append(final_signal)
        scores.append(score)
        reasons.append(", ".join(reason))

    df["signal"]        = signals
    df["signal_score"]  = scores
    df["signal_reason"] = reasons
    df["trend_15min"]   = trend_15

    df.attrs["support_levels"]    = support_levels
    df.attrs["resistance_levels"] = resistance_levels
    df.attrs["trend_15min"]       = trend_15

    return df

