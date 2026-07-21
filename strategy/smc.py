import pandas as pd
from utils.logger import get_logger

log = get_logger("smc")


def get_previous_day_levels(df: pd.DataFrame) -> dict:
    if "timestamp" not in df.columns or len(df) < 10:
        return {}
    try:
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["date"]      = df["timestamp"].dt.date
        dates           = sorted(df["date"].unique())
        if len(dates) < 2:
            return {}
        prev_day    = dates[-2]
        prev_df     = df[df["date"] == prev_day]
        if prev_df.empty:
            return {}
        pdh          = float(prev_df["high"].max())
        pdl          = float(prev_df["low"].min())
        current      = float(df.iloc[-1]["close"])
        return {
            "pdh":      pdh,
            "pdl":      pdl,
            "current":  current,
            "near_pdh": abs(current - pdh) <= 30,
            "near_pdl": abs(current - pdl) <= 30,
            "above_pdh": current > pdh,
            "below_pdl": current < pdl,
        }
    except Exception as e:
        log.error(f"PDH/PDL error: {e}")
        return {}


def pdh_pdl_score(levels: dict, signal: str) -> tuple:
    if not levels:
        return 0, ""
    adj, reasons = 0, []
    if signal == "BUY":
        if levels.get("near_pdl"):
            adj += 15
            reasons.append(f"near PDL {levels['pdl']:.0f}")
        if levels.get("above_pdh"):
            adj += 10
            reasons.append(f"above PDH breakout")
        if levels.get("near_pdh") and not levels.get("above_pdh"):
            adj -= 10
            reasons.append(f"near PDH resistance")
    elif signal == "SELL":
        if levels.get("near_pdh"):
            adj += 15
            reasons.append(f"near PDH {levels['pdh']:.0f}")
        if levels.get("below_pdl"):
            adj += 10
            reasons.append(f"below PDL breakdown")
        if levels.get("near_pdl") and not levels.get("below_pdl"):
            adj -= 10
            reasons.append(f"near PDL support")
    return adj, " | ".join(reasons)


def find_fvgs(df: pd.DataFrame, lookback: int = 50) -> list:
    if len(df) < 3:
        return []
    fvgs   = []
    recent = df.tail(lookback).reset_index(drop=True)
    for i in range(2, len(recent)):
        c0 = recent.iloc[i - 2]
        c2 = recent.iloc[i]
        if float(c2["low"]) > float(c0["high"]):
            fvgs.append({
                "type":   "bullish",
                "bottom": float(c0["high"]),
                "top":    float(c2["low"]),
            })
        elif float(c2["high"]) < float(c0["low"]):
            fvgs.append({
                "type":   "bearish",
                "top":    float(c0["low"]),
                "bottom": float(c2["high"]),
            })
    return fvgs


def fvg_score(df: pd.DataFrame, signal: str) -> tuple:
    if len(df) < 10:
        return 0, ""
    try:
        fvgs    = find_fvgs(df)
        current = float(df.iloc[-1]["close"])
        for fvg in reversed(fvgs):
            inside = fvg["bottom"] <= current <= fvg["top"]
            if not inside:
                continue
            if fvg["type"] == "bullish" and signal == "BUY":
                return 15, f"inside bullish FVG {fvg['bottom']:.0f}-{fvg['top']:.0f}"
            if fvg["type"] == "bearish" and signal == "SELL":
                return 15, f"inside bearish FVG {fvg['bottom']:.0f}-{fvg['top']:.0f}"
        return 0, ""
    except Exception as e:
        log.error(f"FVG error: {e}")
        return 0, ""


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 10) -> dict:
    if len(df) < lookback + 2:
        return {}
    try:
        recent  = df.tail(lookback + 2).reset_index(drop=True)
        window  = recent.iloc[:-1]
        current = recent.iloc[-1]
        w_high  = float(window["high"].max())
        w_low   = float(window["low"].min())
        c_high  = float(current["high"])
        c_low   = float(current["low"])
        c_close = float(current["close"])
        c_open  = float(current["open"])
        body    = c_close - c_open
        atr     = float(df.tail(14)["high"].sub(df.tail(14)["low"]).mean())
        min_body = atr * 0.4
        result  = {"bullish_sweep": False, "bearish_sweep": False,
                   "sweep_low": w_low, "sweep_high": w_high}
        if c_low < w_low and body > min_body:
            result["bullish_sweep"] = True
            result["sweep_low"]     = c_low
            log.info(f"Bullish sweep at {c_low:.1f}")
        if c_high > w_high and body < -min_body:
            result["bearish_sweep"] = True
            result["sweep_high"]    = c_high
            log.info(f"Bearish sweep at {c_high:.1f}")
        return result
    except Exception as e:
        log.error(f"Sweep error: {e}")
        return {}


def sweep_score(sweep: dict, signal: str) -> tuple:
    if not sweep:
        return 0, ""
    if sweep.get("bullish_sweep"):
        if signal == "BUY":
            return 20, f"bullish sweep at {sweep['sweep_low']:.0f}"
        if signal == "SELL":
            return -20, "SELL against bullish sweep"
    if sweep.get("bearish_sweep"):
        if signal == "SELL":
            return 20, f"bearish sweep at {sweep['sweep_high']:.0f}"
        if signal == "BUY":
            return -20, "BUY against bearish sweep"
    return 0, ""


def get_smc_score(df: pd.DataFrame, signal: str) -> tuple:
    """
    Master SMC function called from signal_engine.
    Returns (total_score_adjustment, reasons_string).
    """
    from datetime import datetime, time as dtime
    if not signal or len(df) < 20:
        return 0, ""
    # Only run SMC during market hours
    now = datetime.now().time()
    if not (dtime(9, 15) <= now <= dtime(15, 30)):
        return 0, ""

    total = 0
    reasons = []

    levels       = get_previous_day_levels(df)
    adj, rsn     = pdh_pdl_score(levels, signal)
    total       += adj
    if rsn:
        reasons.append(rsn)

    adj, rsn     = fvg_score(df, signal)
    total       += adj
    if rsn:
        reasons.append(rsn)

    sweep        = detect_liquidity_sweep(df)
    adj, rsn     = sweep_score(sweep, signal)
    total       += adj
    if rsn:
        reasons.append(rsn)

    if total != 0:
        log.debug(f"SMC: {'+' if total>0 else ''}{total} | {' | '.join(reasons)}")

    return total, " | ".join(reasons)
