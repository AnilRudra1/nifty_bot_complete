"""
Put Call Ratio (PCR) Filter

PCR = Total Put OI / Total Call OI across all Nifty strikes.

PCR > 1.2  = Too many puts = Contrarian BULLISH bias
             Favour: BUY CE, SELL PE

PCR 0.8-1.2 = Neutral = Take signals both directions

PCR < 0.8  = Too many calls = Contrarian BEARISH bias
             Favour: BUY PE, SELL CE

Fetched from Angel One option chain every 30 minutes.
"""

import time
from datetime import datetime
from utils.logger import get_logger

log = get_logger("pcr_filter")

# Cache
_pcr_cache = {
    "value":      None,
    "total_ce":   0,
    "total_pe":   0,
    "last_fetch": None,
    "strikes":    {},
}

PCR_FETCH_INTERVAL = 1800   # 30 minutes
PCR_BULLISH        = 1.2    # above this = bullish bias
PCR_BEARISH        = 0.8    # below this = bearish bias


def fetch_pcr(client) -> dict:
    """
    Fetch Nifty option chain and calculate PCR.
    Returns dict with pcr, total_ce_oi, total_pe_oi, bias.
    """
    try:
        resp = client.smart_api.optionGreeks({
            "name":        "NIFTY",
            "expirydate":  ""   # nearest expiry
        })

        if not resp or not resp.get("status"):
            log.warning("Option chain fetch failed")
            return {}

        data     = resp.get("data", [])
        total_ce = 0
        total_pe = 0
        strikes  = {}

        for item in data:
            strike    = item.get("strikePrice", 0)
            ce_oi     = float(item.get("CE", {}).get("openInterest", 0))
            pe_oi     = float(item.get("PE", {}).get("openInterest", 0))
            total_ce += ce_oi
            total_pe += pe_oi
            strikes[strike] = {"ce_oi": ce_oi, "pe_oi": pe_oi}

        if total_ce == 0:
            return {}

        pcr = round(total_pe / total_ce, 3)

        if pcr > PCR_BULLISH:
            bias = "BULLISH"
        elif pcr < PCR_BEARISH:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        result = {
            "pcr":       pcr,
            "total_ce":  total_ce,
            "total_pe":  total_pe,
            "bias":      bias,
            "strikes":   strikes,
        }

        log.info(f"PCR: {pcr:.3f} | CE OI: {total_ce:,.0f} | PE OI: {total_pe:,.0f} | Bias: {bias}")
        return result

    except Exception as e:
        log.error(f"PCR fetch error: {e}")
        return {}


def update_pcr(client) -> dict:
    """
    Update PCR cache if 30 minutes have passed.
    Returns current PCR data.
    """
    now  = datetime.now()
    last = _pcr_cache.get("last_fetch")

    if last and (now - last).seconds < PCR_FETCH_INTERVAL:
        return _pcr_cache

    data = fetch_pcr(client)
    if data:
        _pcr_cache.update(data)
        _pcr_cache["last_fetch"] = now

    return _pcr_cache


def get_pcr_bias() -> str:
    """Returns current PCR bias: BULLISH, BEARISH, or NEUTRAL."""
    return _pcr_cache.get("bias", "NEUTRAL")


def get_pcr_value() -> float:
    """Returns current PCR value."""
    return _pcr_cache.get("pcr", 1.0) or 1.0


def confirm_signal_with_pcr(signal: str, option_type: str) -> tuple:
    """
    Check if signal aligns with PCR bias.

    Returns (confirmed: bool, reason: str, score_adj: int)

    BULLISH PCR + BUY CE  = aligned (+10 bonus)
    BULLISH PCR + SELL PE = aligned (+10 bonus)
    BULLISH PCR + BUY PE  = contradicts (-10 penalty)
    BULLISH PCR + SELL CE = contradicts (-10 penalty)

    BEARISH PCR + BUY PE  = aligned (+10 bonus)
    BEARISH PCR + SELL CE = aligned (+10 bonus)
    BEARISH PCR + BUY CE  = contradicts (-10 penalty)
    BEARISH PCR + SELL PE = contradicts (-10 penalty)

    NEUTRAL PCR = no adjustment either way
    """
    bias = get_pcr_bias()
    pcr  = get_pcr_value()

    if bias == "NEUTRAL":
        return True, f"PCR {pcr:.2f} neutral", 0

    aligned = False

    if bias == "BULLISH":
        if (signal == "BUY"  and option_type == "CE") or \
           (signal == "SELL" and option_type == "PE"):
            aligned = True
        else:
            aligned = False

    elif bias == "BEARISH":
        if (signal == "BUY"  and option_type == "PE") or \
           (signal == "SELL" and option_type == "CE"):
            aligned = True
        else:
            aligned = False

    if aligned:
        return True, f"PCR {pcr:.2f} ({bias}) aligns with {signal} {option_type}", 10
    else:
        return True, f"PCR {pcr:.2f} ({bias}) contradicts {signal} {option_type}", -10


def get_max_pain(strikes: dict, spot: float) -> float:
    """
    Calculate max pain strike — where maximum options expire worthless.
    This is where Nifty tends to gravitate towards on expiry day.
    """
    if not strikes:
        return spot

    pain = {}
    for strike, oi in strikes.items():
        try:
            s    = float(strike)
            loss = 0
            for other_strike, other_oi in strikes.items():
                os = float(other_strike)
                # Loss to call writers if Nifty settles at this strike
                if os < s:
                    loss += other_oi.get("ce_oi", 0) * (s - os)
                # Loss to put writers if Nifty settles at this strike
                if os > s:
                    loss += other_oi.get("pe_oi", 0) * (os - s)
            pain[s] = loss
        except Exception:
            continue

    if not pain:
        return spot

    max_pain_strike = min(pain, key=pain.get)
    log.info(f"Max pain strike: {max_pain_strike}")
    return max_pain_strike
