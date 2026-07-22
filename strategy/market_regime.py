"""
Market Regime Detector

Determines at 10:00 AM whether today is TRENDING or CHOPPY.
This single check changes position sizing and score threshold
without touching any of the signal logic.

TRENDING day  → full size 2 lots, score 60
MODERATE day  → full size 2 lots, score 65
CHOPPY day    → half size 1 lot,  score 75, stop after 1 PM
"""

import pandas as pd
from datetime import datetime, time as dtime
from utils.logger import get_logger

log = get_logger("regime")

_regime_cache = {
    "regime":       "UNKNOWN",
    "detected_at":  None,
    "range_45min":  0,
    "direction":    0,
    "details":      "",
}


def detect_regime(nifty_df: pd.DataFrame) -> str:
    """
    Detect market regime from first 45 minutes of Nifty data.
    Call this once after 10:00 AM.

    Returns: TRENDING, MODERATE, or CHOPPY
    """
    if nifty_df.empty or len(nifty_df) < 5:
        return "UNKNOWN"

    try:
        open_price   = float(nifty_df.iloc[0]["open"])
        current      = float(nifty_df.iloc[-1]["close"])
        high_45      = float(nifty_df["high"].max())
        low_45       = float(nifty_df["low"].min())
        range_45min  = high_45 - low_45
        direction    = abs(current - open_price)

        # Count bullish vs bearish candles
        bull_candles = len(nifty_df[nifty_df["close"] > nifty_df["open"]])
        bear_candles = len(nifty_df[nifty_df["close"] < nifty_df["open"]])
        total        = len(nifty_df)
        dominance    = abs(bull_candles - bear_candles) / total

        details = (
            f"Range:{range_45min:.0f}pts | "
            f"Direction:{direction:.0f}pts | "
            f"Bull:{bull_candles} Bear:{bear_candles} | "
            f"Dominance:{dominance:.0%}"
        )

        # Trending — wide range, strong directional move, one side dominant
        if range_45min > 80 and direction > 50 and dominance > 0.5:
            regime = "TRENDING"
        # Choppy — narrow range, no direction, mixed candles
        elif range_45min < 60 and direction < 30 and dominance < 0.3:
            regime = "CHOPPY"
        # Moderate — everything in between
        else:
            regime = "MODERATE"

        _regime_cache.update({
            "regime":      regime,
            "detected_at": datetime.now().isoformat(),
            "range_45min": range_45min,
            "direction":   direction,
            "details":     details,
        })

        log.info(f"Market regime: {regime} | {details}")
        return regime

    except Exception as e:
        log.error(f"Regime detection error: {e}")
        return "UNKNOWN"


def get_regime() -> str:
    return _regime_cache.get("regime", "UNKNOWN")


def get_regime_settings(regime: str) -> dict:
    """
    Returns trading settings based on market regime.
    """
    settings = {
        "TRENDING": {
            "lots":       2,
            "score_min":  60,
            "stop_after": 15,    # hour to stop new entries
            "note":       "Full size — trending day",
        },
        "MODERATE": {
            "lots":       2,
            "score_min":  65,
            "stop_after": 15,
            "note":       "Full size — moderate day",
        },
        "CHOPPY": {
            "lots":       1,
            "score_min":  75,
            "stop_after": 13,    # stop at 1 PM on choppy days
            "note":       "Half size — choppy day, stop at 1 PM",
        },
        "UNKNOWN": {
            "lots":       2,
            "score_min":  65,
            "stop_after": 15,
            "note":       "Default settings",
        },
    }
    return settings.get(regime, settings["UNKNOWN"])


def should_stop_trading(regime: str) -> bool:
    """Check if we should stop new entries based on regime and time."""
    settings = get_regime_settings(regime)
    stop_hr  = settings.get("stop_after", 15)
    return datetime.now().hour >= stop_hr
