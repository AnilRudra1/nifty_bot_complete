"""
Signal engine. Combines:
  - Candlestick pattern (direction + confidence)
  - RSI confirmation (oversold for BUY, overbought for SELL)
  - VWAP filter (above for BUY, below for SELL)
  - EMA trend filter (fast > slow for BUY, fast < slow for SELL)
  - Volume surge (volume must be above average to confirm)
  - ADX trend filter (skip signals in choppy/sideways markets)
  - Support/resistance proximity

Scoring:
  HIGH confidence pattern  = 40 points
  MEDIUM confidence pattern= 25 points
  RSI confirms             = +15 points
  VWAP confirms            = +15 points
  EMA confirms             = +10 points
  Volume surge             = +10 points
  Near S/R level           = +10 points
  Total possible           = 100 points

Signal only fires if:
  - Score >= 50 (medium pattern + at least 2 confirmations)
  - Market is trending (ADX > threshold)
"""

import pandas as pd
from config import Config
from strategy.candlestick_patterns import apply_all_patterns, get_pattern_signal
from strategy.indicators import add_all_indicators
from strategy.support_resistance import get_sr_levels, is_near_level


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = apply_all_patterns(df)
    df = add_all_indicators(df)

    support_levels, resistance_levels = get_sr_levels(df)
    df["near_support"]    = df["low"].apply(lambda p: is_near_level(p, support_levels) is not None)
    df["near_resistance"] = df["high"].apply(lambda p: is_near_level(p, resistance_levels) is not None)

    signals, scores, reasons = [], [], []

    for i, row in df.iterrows():
        direction, confidence = get_pattern_signal(row)
        score  = 0
        reason = []

        if direction is None:
            signals.append(None); scores.append(0); reasons.append(""); continue

        # Base score from pattern confidence
        if confidence == "HIGH":
            score += 40; reason.append(f"HIGH pattern")
        elif confidence == "MEDIUM":
            score += 25; reason.append(f"MED pattern")

        # RSI confirmation
        rsi = row.get("rsi", 50)
        if direction == "BUY" and rsi < Config.RSI_OVERSOLD:
            score += 15; reason.append(f"RSI {rsi:.0f} oversold")
        elif direction == "SELL" and rsi > Config.RSI_OVERBOUGHT:
            score += 15; reason.append(f"RSI {rsi:.0f} overbought")

        # VWAP filter
        if direction == "BUY" and row.get("above_vwap"):
            score += 15; reason.append("above VWAP")
        elif direction == "SELL" and row.get("below_vwap"):
            score += 15; reason.append("below VWAP")

        # EMA filter
        if direction == "BUY" and row.get("ema_bull"):
            score += 10; reason.append("EMA bullish")
        elif direction == "SELL" and row.get("ema_bear"):
            score += 10; reason.append("EMA bearish")

        # Volume surge
        if row.get("vol_surge"):
            score += 10; reason.append("volume surge")

        # S/R proximity
        if direction == "BUY" and row.get("near_support"):
            score += 10; reason.append("at support")
        elif direction == "SELL" and row.get("near_resistance"):
            score += 10; reason.append("at resistance")

        # ADX trend filter — if not trending, zero out the score
        if not row.get("is_trending", True):
            score = 0; reason = ["market sideways (ADX low)"]

        # Only emit signal if score meets minimum threshold
        if score >= 50:
            signals.append(direction)
        else:
            signals.append(None)

        scores.append(score)
        reasons.append(", ".join(reason))

    df["signal"]       = signals
    df["signal_score"] = scores
    df["signal_reason"]= reasons
    df.attrs["support_levels"]    = support_levels
    df.attrs["resistance_levels"] = resistance_levels
    return df
