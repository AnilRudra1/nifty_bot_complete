"""
Support and resistance detection using pivot highs/lows + level clustering.
Also includes classic floor-trader pivot points (P, R1-R3, S1-S3).
"""

import numpy as np
import pandas as pd
from config import Config


def find_pivots(df: pd.DataFrame, lookback: int = None) -> pd.DataFrame:
    lookback = lookback or Config.SR_LOOKBACK
    df = df.copy()
    df["pivot_high"] = False
    df["pivot_low"]  = False
    highs = df["high"].values
    lows  = df["low"].values
    for i in range(lookback, len(df) - lookback):
        if highs[i] == highs[i - lookback:i + lookback + 1].max():
            df.iat[i, df.columns.get_loc("pivot_high")] = True
        if lows[i] == lows[i - lookback:i + lookback + 1].min():
            df.iat[i, df.columns.get_loc("pivot_low")]  = True
    return df


def cluster_levels(prices: list, tol_pct: float = None) -> list:
    tol_pct = tol_pct or Config.SR_TOLERANCE_PCT
    if not prices:
        return []
    prices = sorted(prices)
    clusters = [[prices[0]]]
    for p in prices[1:]:
        avg = sum(clusters[-1]) / len(clusters[-1])
        if abs(p - avg) / avg * 100 <= tol_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [round(sum(c) / len(c), 2) for c in clusters]


def get_sr_levels(df: pd.DataFrame):
    """Returns (support_levels, resistance_levels) as sorted price lists."""
    df = find_pivots(df)
    res = cluster_levels(df.loc[df["pivot_high"], "high"].tolist())
    sup = cluster_levels(df.loc[df["pivot_low"],  "low"].tolist())
    return sorted(sup), sorted(res)


def classic_pivots(prev_high, prev_low, prev_close) -> dict:
    p  = (prev_high + prev_low + prev_close) / 3
    return {
        "pivot": round(p, 2),
        "r1": round(2*p - prev_low, 2),
        "r2": round(p + (prev_high - prev_low), 2),
        "r3": round(prev_high + 2*(p - prev_low), 2),
        "s1": round(2*p - prev_high, 2),
        "s2": round(p - (prev_high - prev_low), 2),
        "s3": round(prev_low - 2*(prev_high - p), 2),
    }


def is_near_level(price: float, levels: list, tol_pct: float = None) -> float | None:
    tol_pct = tol_pct or Config.SR_TOLERANCE_PCT
    for lvl in levels:
        if abs(price - lvl) / lvl * 100 <= tol_pct:
            return lvl
    return None
