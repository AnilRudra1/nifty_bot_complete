import requests
import pandas as pd
from utils.logger import get_logger

log = get_logger("option_filter")


def get_india_vix(angel_client=None) -> float:
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer":    "https://www.nseindia.com",
        })
        session.get("https://www.nseindia.com", timeout=5)
        resp = session.get("https://www.nseindia.com/api/allIndices", timeout=5)
        if resp.status_code == 200:
            for idx in resp.json().get("data", []):
                if "VIX" in idx.get("indexSymbol", ""):
                    vix = float(idx.get("last", 0))
                    if vix > 0:
                        log.info(f"India VIX: {vix}")
                        return vix
    except Exception as e:
        log.debug(f"NSE VIX failed: {e}")

    if angel_client:
        try:
            ltp = angel_client.get_ltp("NSE", "India VIX", "99919000")
            if ltp and ltp > 0:
                log.info(f"India VIX (Angel): {ltp}")
                return float(ltp)
        except Exception as e:
            log.debug(f"Angel VIX failed: {e}")

    log.warning("VIX unavailable, using default 15.0")
    return 15.0


def is_vix_safe(vix: float) -> tuple:
    if vix > 22:
        return False, f"VIX {vix:.1f} too high — premiums expensive"
    if vix > 18:
        return True, f"VIX {vix:.1f} elevated — trade carefully"
    return True, f"VIX {vix:.1f} normal"


def estimate_iv_rank(candles: list, lookback: int = 20) -> float:
    if len(candles) < lookback:
        return 50.0
    closes  = [float(c.get("close", 0)) for c in candles[-lookback:]]
    current = closes[-1]
    low20   = min(closes)
    high20  = max(closes)
    if high20 == low20:
        return 50.0
    return round((current - low20) / (high20 - low20) * 100, 1)


def is_iv_rank_ok(iv_rank: float, max_rank: float = 70.0) -> tuple:
    if iv_rank > max_rank:
        return False, f"IV rank {iv_rank:.0f} too high"
    return True, f"IV rank {iv_rank:.0f} ok"


def check_option_volume(candles: list, lookback: int = 10, min_surge: float = 1.2) -> tuple:
    if len(candles) < lookback:
        return True, "Not enough data"
    vols    = [float(c.get("volume", 0)) for c in candles[-lookback:]]
    current = vols[-1]
    avg     = sum(vols[:-1]) / max(len(vols) - 1, 1)
    if avg == 0:
        return True, "No volume data"
    surge = current / avg
    if surge >= min_surge:
        return True, f"Volume surge {surge:.1f}x"
    return False, f"Low volume {surge:.1f}x"


def estimate_delta(spot: float, strike: float, option_type: str) -> float:
    if spot <= 0 or strike <= 0:
        return 0.5
    moneyness = (spot - strike) / spot * 100
    if option_type.upper() == "PE":
        moneyness = -moneyness
    if moneyness >= 2:   return 0.70
    if moneyness >= 0:   return 0.50
    if moneyness >= -1:  return 0.35
    if moneyness >= -2:  return 0.20
    return 0.10


def is_delta_ok(delta: float, min_delta: float = 0.25) -> tuple:
    if delta < min_delta:
        return False, f"Delta {delta:.2f} too low"
    return True, f"Delta {delta:.2f} ok"


def option_quality_check(symbol, option_type, strike, spot, candles, vix=15.0) -> tuple:
    bonus  = 0
    failed = []
    results= []

    vix_ok, vix_reason = is_vix_safe(vix)
    results.append(vix_reason)
    if not vix_ok:
        failed.append("VIX")
    elif vix < 15:
        bonus += 5

    iv_rank      = estimate_iv_rank(candles)
    iv_ok, iv_r  = is_iv_rank_ok(iv_rank)
    results.append(iv_r)
    if iv_ok:
        bonus += 10 if iv_rank < 30 else 5 if iv_rank < 50 else 0
    else:
        failed.append("IV_RANK")

    vol_ok, vol_r = check_option_volume(candles)
    results.append(vol_r)
    if vol_ok:
        bonus += 10

    delta         = estimate_delta(spot, strike, option_type)
    d_ok, d_r     = is_delta_ok(delta)
    results.append(d_r)
    if d_ok:
        bonus += 5 if delta >= 0.5 else 0
    else:
        failed.append("DELTA")

    passed = len(failed) == 0
    log.info(f"[{symbol}] Filter | VIX:{vix:.1f} IV:{iv_rank:.0f} Delta:{delta:.2f} | +{bonus} | {'PASS' if passed else 'FAIL:'+','.join(failed)}")
    return passed, bonus, results
