"""
Open Interest Filter

OI change direction is the most reliable confirmation of whether
a price move is real (backed by new money) or fake (just covering).

Price UP + OI UP   = Fresh buying   = REAL move = CONFIRM BUY
Price UP + OI DOWN = Short covering = FAKE move = REJECT
Price DN + OI UP   = Fresh selling  = REAL move = CONFIRM SELL
Price DN + OI DOWN = Long unwinding = FAKE move = REJECT

Angel One API provides OI through getMarketData endpoint.
We fetch OI every 15 minutes per instrument and track change.
"""

import time
from datetime import datetime, timedelta
from collections import defaultdict
from utils.logger import get_logger

log = get_logger("oi_filter")

# Store OI history per token
# {token: [(timestamp, oi), ...]}
_oi_history = defaultdict(list)
_last_fetch  = {}   # token -> datetime of last fetch
OI_FETCH_INTERVAL = 900   # 15 minutes in seconds
OI_MIN_CHANGE_PCT = 0.5   # minimum 0.5% OI change to consider significant


def fetch_oi(client, symbol: str, token: str, exchange: str = "NFO") -> float:
    """
    Fetch current Open Interest for a specific instrument.
    Returns OI value or 0 if unavailable.
    """
    try:
        resp = client.smart_api.getMarketData(
            mode="FULL",
            exchangeTokens={exchange: [token]}
        )
        if resp and resp.get("status"):
            data     = resp.get("data", {})
            fetched  = data.get("fetched", [])
            if fetched:
                oi = float(fetched[0].get("openInterest", 0))
                log.debug(f"OI [{symbol}]: {oi:,.0f}")
                return oi
    except Exception as e:
        log.debug(f"OI fetch error [{symbol}]: {e}")
    return 0.0


def update_oi(client, symbol: str, token: str, exchange: str = "NFO") -> float:
    """
    Update OI history for an instrument.
    Only fetches from API if 15 minutes have passed since last fetch.
    Returns current OI.
    """
    now      = datetime.now()
    last     = _last_fetch.get(token)

    if last and (now - last).seconds < OI_FETCH_INTERVAL:
        # Return last known OI without API call
        history = _oi_history.get(token, [])
        return history[-1][1] if history else 0.0

    oi = fetch_oi(client, symbol, token, exchange)
    if oi > 0:
        _oi_history[token].append((now, oi))
        _last_fetch[token] = now
        # Keep only last 20 readings (5 hours of data)
        if len(_oi_history[token]) > 20:
            _oi_history[token] = _oi_history[token][-20:]

    return oi


def get_oi_change(token: str) -> dict:
    """
    Get OI change statistics for an instrument.
    Compares current OI to OI from 15-30 minutes ago.
    Returns dict with change direction, amount and percentage.
    """
    history = _oi_history.get(token, [])

    if len(history) < 2:
        return {
            "direction":  "UNKNOWN",
            "change":     0,
            "change_pct": 0,
            "current":    history[-1][1] if history else 0,
            "previous":   0,
        }

    current  = history[-1][1]
    previous = history[-2][1]

    if previous == 0:
        return {
            "direction":  "UNKNOWN",
            "change":     0,
            "change_pct": 0,
            "current":    current,
            "previous":   previous,
        }

    change     = current - previous
    change_pct = abs(change / previous * 100)

    if change_pct < OI_MIN_CHANGE_PCT:
        direction = "FLAT"    # OI barely moved — not significant
    elif change > 0:
        direction = "RISING"  # new positions being opened
    else:
        direction = "FALLING" # positions being closed

    return {
        "direction":  direction,
        "change":     round(change, 0),
        "change_pct": round(change_pct, 2),
        "current":    current,
        "previous":   previous,
    }


def confirm_signal_with_oi(token: str, signal: str) -> tuple:
    """
    Core function — confirms or rejects a signal based on OI change.

    Returns (confirmed: bool, reason: str, score_adj: int)

    BUY signal + OI RISING  = confirmed (+15 bonus)
    BUY signal + OI FALLING = rejected  (short covering, price will reverse)
    BUY signal + OI FLAT    = neutral   (no adjustment)

    SELL signal + OI RISING  = confirmed (+15 bonus)
    SELL signal + OI FALLING = rejected  (long unwinding, price will reverse)
    SELL signal + OI FLAT    = neutral   (no adjustment)
    """
    oi = get_oi_change(token)
    direction = oi["direction"]
    change_pct = oi["change_pct"]

    if direction == "UNKNOWN":
        return True, "OI unknown — allowing (no data yet)", 0

    if direction == "FLAT":
        return True, f"OI flat ({change_pct:.1f}% change) — neutral", 0

    if signal == "BUY":
        if direction == "RISING":
            return True, f"OI rising +{oi['change']:,.0f} — fresh buying confirmed", 15
        else:
            return False, f"OI falling {oi['change']:,.0f} — short covering, skip", 0

    elif signal == "SELL":
        if direction == "RISING":
            return True, f"OI rising +{oi['change']:,.0f} — fresh selling confirmed", 15
        else:
            return False, f"OI falling {oi['change']:,.0f} — long unwinding, skip", 0

    return True, "OI check passed", 0
