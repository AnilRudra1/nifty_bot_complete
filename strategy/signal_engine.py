"""
Signal engine.

Reads patterns + indicators on NIFTY SPOT candles (not option premiums).
Patterns on the underlying index are meaningful — patterns on option
premiums are noise.

Scoring:
  HIGH confidence pattern  = 40 pts
  MEDIUM confidence pattern= 25 pts
  RSI confirms             = +15 pts
  VWAP confirms            = +15 pts
  EMA confirms             = +10 pts
  Volume surge             = +10 pts
  Near S/R level           = +10 pts
  Max possible             = 100 pts

Signal fires only if score >= Config.SIGNAL_SCORE_MIN (default 65)
and market is trending (ADX > threshold).
"""

import pandas as pd
from config import Config
from strategy.candlestick_patterns import apply_all_patterns, get_pattern_signal
from strategy.indicators import add_all_indicators
from strategy.support_resistance import get_sr_levels, is_near_level


def get_market_direction(df: pd.DataFrame) -> str:
    """
    Detect overall market direction from recent candles.
    Uses EMA trend + VWAP position on last 6 candles.
    Returns 'BULL', 'BEAR', or 'NEUTRAL'.
    """
    if len(df) < 10:
        return "NEUTRAL"
    recent = df.tail(6)
    bull_count = sum(
        1 for _, r in recent.iterrows()
        if r.get("ema_bull", False) and r.get("above_vwap", False)
    )
    bear_count = sum(
        1 for _, r in recent.iterrows()
        if r.get("ema_bear", False) and r.get("below_vwap", False)
    )
    if bull_count >= 4:
        return "BULL"
    if bear_count >= 4:
        return "BEAR"
    return "NEUTRAL"


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes raw OHLCV DataFrame (Nifty spot candles),
    returns it with pattern columns, indicator columns,
    and a 'signal' column: 'BUY', 'SELL', or None.

    Also adds 'signal_score' and 'signal_reason' columns.
    """
    df = apply_all_patterns(df)
    df = add_all_indicators(df)

    support_levels, resistance_levels = get_sr_levels(df)

    df["near_support"]    = df["low"].apply(
        lambda p: is_near_level(p, support_levels) is not None
    )
    df["near_resistance"] = df["high"].apply(
        lambda p: is_near_level(p, resistance_levels) is not None
    )

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

        # Base score from pattern confidence
        if confidence == "HIGH":
            score += 40
            reason.append("HIGH pattern")
        elif confidence == "MEDIUM":
            score += 25
            reason.append("MED pattern")

        # RSI confirmation
        rsi = row.get("rsi", 50) or 50
        if direction == "BUY" and rsi < Config.RSI_OVERSOLD:
            score += 15
            reason.append(f"RSI {rsi:.0f} oversold")
        elif direction == "SELL" and rsi > Config.RSI_OVERBOUGHT:
            score += 15
            reason.append(f"RSI {rsi:.0f} overbought")

        # VWAP filter
        if direction == "BUY" and row.get("above_vwap"):
            score += 15
            reason.append("above VWAP")
        elif direction == "SELL" and row.get("below_vwap"):
            score += 15
            reason.append("below VWAP")

        # EMA filter
        if direction == "BUY" and row.get("ema_bull"):
            score += 10
            reason.append("EMA bullish")
        elif direction == "SELL" and row.get("ema_bear"):
            score += 10
            reason.append("EMA bearish")

        # Volume surge
        if row.get("vol_surge"):
            score += 10
            reason.append("volume surge")

        # S/R proximity
        if direction == "BUY" and row.get("near_support"):
            score += 10
            reason.append("at support")
        elif direction == "SELL" and row.get("near_resistance"):
            score += 10
            reason.append("at resistance")

        # ADX trend filter — zero out score if market is sideways
        if not row.get("is_trending", True):
            score  = 0
            reason = ["sideways (ADX low)"]

        signals.append(direction if score >= Config.SIGNAL_SCORE_MIN else None)
        scores.append(score)
        reasons.append(", ".join(reason))

    df["signal"]        = signals
    df["signal_score"]  = scores
    df["signal_reason"] = reasons

    df.attrs["support_levels"]    = support_levels
    df.attrs["resistance_levels"] = resistance_levels

    return df