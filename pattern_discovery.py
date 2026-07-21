"""
Pattern Discovery Script

Run this after one month of tick data collection.
Analyzes all recorded ticks and discovers what conditions
consistently preceded 20-point moves.

Usage:
    python3 pattern_discovery.py

Output:
    - Top conditions that preceded big moves
    - Custom pattern rules with accuracy statistics
    - Comparison against traditional candlestick patterns
    - Recommended entry rules for the trading bot
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from glob import glob

DATA_DIR    = "data/tick_data"
REPORT_DIR  = "data/discovery_reports"
MIN_SAMPLES = 30   # minimum occurrences needed to trust a pattern


def load_all_ticks() -> pd.DataFrame:
    """Load all tick CSV files from data directory."""
    files = glob(f"{DATA_DIR}/*.csv")
    if not files:
        print(f"No data files found in {DATA_DIR}")
        return pd.DataFrame()

    dfs = []
    for f in sorted(files):
        try:
            df = pd.read_csv(f)
            dfs.append(df)
        except Exception as e:
            print(f"Error loading {f}: {e}")

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)
    print(f"Loaded {len(combined):,} ticks from {len(files)} files")
    return combined


def basic_stats(df: pd.DataFrame):
    """Print basic statistics about the data."""
    print("\n" + "="*60)
    print(" DATA OVERVIEW")
    print("="*60)
    print(f"Total ticks         : {len(df):,}")
    print(f"Trading days        : {df['date'].nunique()}")
    print(f"Instruments         : {df['symbol'].nunique()}")
    print(f"Date range          : {df['date'].min()} to {df['date'].max()}")

    big_up   = df["big_move_up"].sum()
    big_down = df["big_move_down"].sum()
    print(f"\nBig move up setups  : {big_up:,} ({big_up/len(df)*100:.1f}% of ticks)")
    print(f"Big move down setups: {big_down:,} ({big_down/len(df)*100:.1f}% of ticks)")
    print(f"Total big move setups: {big_up + big_down:,}")


def analyze_time_of_day(df: pd.DataFrame):
    """Find which times of day have most big moves."""
    print("\n" + "="*60)
    print(" TIME OF DAY ANALYSIS")
    print("="*60)
    print(f"\n{'Hour':<8} {'Ticks':>8} {'BigMoveUp':>10} {'BigMoveDown':>12} {'Total%':>8}")
    print("-"*50)

    for hour in range(9, 16):
        hour_df  = df[df["hour"] == hour]
        if len(hour_df) == 0:
            continue
        bmu  = hour_df["big_move_up"].sum()
        bmd  = hour_df["big_move_down"].sum()
        pct  = (bmu + bmd) / len(hour_df) * 100
        print(f"{hour}:00    {len(hour_df):>8,} {bmu:>10,} {bmd:>12,} {pct:>7.1f}%")


def analyze_rsi_ranges(df: pd.DataFrame):
    """Find which RSI ranges precede big moves."""
    print("\n" + "="*60)
    print(" RSI RANGES BEFORE BIG MOVES")
    print("="*60)

    bins   = [(0,30), (30,40), (40,50), (50,60), (60,70), (70,100)]
    labels = ["0-30 (Oversold)", "30-40", "40-50", "50-60", "60-70", "70-100 (Overbought)"]

    print(f"\n{'RSI Range':<22} {'Ticks':>7} {'BigUp%':>8} {'BigDown%':>10} {'Total%':>8}")
    print("-"*58)

    for (lo, hi), label in zip(bins, labels):
        subset = df[(df["rsi"] >= lo) & (df["rsi"] < hi)]
        if len(subset) < MIN_SAMPLES:
            continue
        bmu_pct = subset["big_move_up"].mean()   * 100
        bmd_pct = subset["big_move_down"].mean()  * 100
        tot_pct = (bmu_pct + bmd_pct)
        print(f"{label:<22} {len(subset):>7,} {bmu_pct:>7.1f}% {bmd_pct:>9.1f}% {tot_pct:>7.1f}%")


def analyze_vwap_position(df: pd.DataFrame):
    """Find how VWAP position relates to big moves."""
    print("\n" + "="*60)
    print(" VWAP POSITION BEFORE BIG MOVES")
    print("="*60)

    for above, label in [(True, "Above VWAP"), (False, "Below VWAP")]:
        subset = df[df["above_vwap"] == above]
        if len(subset) < MIN_SAMPLES:
            continue
        bmu_pct = subset["big_move_up"].mean()  * 100
        bmd_pct = subset["big_move_down"].mean() * 100
        print(f"\n{label} ({len(subset):,} ticks):")
        print(f"  Big move up    : {bmu_pct:.1f}%")
        print(f"  Big move down  : {bmd_pct:.1f}%")


def analyze_patterns(df: pd.DataFrame):
    """Find which candlestick patterns precede big moves most reliably."""
    print("\n" + "="*60)
    print(" PATTERN PERFORMANCE (custom from your data)")
    print("="*60)

    patterns = df[df["pattern"] != ""]["pattern"].unique()
    results  = []

    for pat in patterns:
        subset = df[df["pattern"] == pat]
        if len(subset) < MIN_SAMPLES:
            continue
        bmu_pct  = subset["big_move_up"].mean()   * 100
        bmd_pct  = subset["big_move_down"].mean()  * 100
        avg_move = subset["move_in_next_5min"].mean()
        results.append({
            "pattern":      pat,
            "count":        len(subset),
            "big_up_pct":   round(bmu_pct,  1),
            "big_down_pct": round(bmd_pct,  1),
            "total_pct":    round(bmu_pct + bmd_pct, 1),
            "avg_5min_move": round(avg_move, 2),
        })

    results.sort(key=lambda x: x["total_pct"], reverse=True)

    print(f"\n{'Pattern':<25} {'Count':>6} {'BigUp%':>8} {'BigDown%':>10} {'Total%':>8} {'Avg5mMove':>10}")
    print("-"*72)
    for r in results:
        print(
            f"{r['pattern']:<25} {r['count']:>6,} "
            f"{r['big_up_pct']:>7.1f}% {r['big_down_pct']:>9.1f}% "
            f"{r['total_pct']:>7.1f}% {r['avg_5min_move']:>9.2f}"
        )


def analyze_combined_conditions(df: pd.DataFrame):
    """
    Find combinations of conditions that reliably precede big moves.
    This is the core pattern discovery — finding multi-condition setups.
    """
    print("\n" + "="*60)
    print(" COMBINED CONDITION ANALYSIS")
    print(" (What conditions together predict 20-point moves)")
    print("="*60)

    conditions = {
        "RSI < 30 (oversold)":          df["rsi"] < 30,
        "RSI > 70 (overbought)":         df["rsi"] > 70,
        "RSI 30-40":                     (df["rsi"] >= 30) & (df["rsi"] < 40),
        "RSI 60-70":                     (df["rsi"] >= 60) & (df["rsi"] < 70),
        "Above VWAP":                    df["above_vwap"] == True,
        "Below VWAP":                    df["above_vwap"] == False,
        "EMA Bullish":                   df["ema_bull"]   == True,
        "EMA Bearish":                   df["ema_bear"]   == True,
        "Volume Surge":                  df["vol_surge"]  == True,
        "Trending (ADX>20)":             df["is_trending"] == True,
        "Morning (9-11)":                df["is_morning"] == True,
        "Afternoon (13-15)":             df["is_afternoon"] == True,
        "Price at day high (within 5pts)": df["dist_from_day_high"] <= 5,
        "Price at day low (within 5pts)":  df["dist_from_day_low"]  <= 5,
        "Strong upward move in 5m":      df["move_5min"] >= 10,
        "Strong downward move in 5m":    df["move_5min"] <= -10,
        "Near flat in 5m (consolidating)": df["move_5min"].abs() <= 3,
    }

    results = []
    baseline_up   = df["big_move_up"].mean()   * 100
    baseline_down = df["big_move_down"].mean()  * 100

    for cond_name, mask in conditions.items():
        subset = df[mask]
        if len(subset) < MIN_SAMPLES:
            continue
        bmu  = subset["big_move_up"].mean()   * 100
        bmd  = subset["big_move_down"].mean()  * 100
        lift = (bmu + bmd) / (baseline_up + baseline_down) if (baseline_up + baseline_down) > 0 else 1.0
        results.append({
            "condition":  cond_name,
            "count":      len(subset),
            "big_up_pct": round(bmu, 1),
            "big_dn_pct": round(bmd, 1),
            "lift":       round(lift, 2),
        })

    results.sort(key=lambda x: x["lift"], reverse=True)

    print(f"\nBaseline (all ticks): {baseline_up:.1f}% up | {baseline_down:.1f}% down")
    print(f"\n{'Condition':<38} {'Count':>7} {'BigUp%':>7} {'BigDn%':>7} {'Lift':>6}")
    print("-"*70)
    for r in results[:15]:
        flag = "🔥" if r["lift"] > 1.5 else "✅" if r["lift"] > 1.2 else "  "
        print(
            f"{flag} {r['condition']:<36} {r['count']:>7,} "
            f"{r['big_up_pct']:>6.1f}% {r['big_dn_pct']:>6.1f}% {r['lift']:>6.2f}x"
        )


def discover_best_entry_setups(df: pd.DataFrame):
    """
    Find the best multi-condition entry setups.
    Combines 2-3 conditions to find highest probability setups.
    """
    print("\n" + "="*60)
    print(" BEST ENTRY SETUPS DISCOVERED")
    print(" (High probability 20-point move setups from your data)")
    print("="*60)

    baseline = (df["big_move_up"].mean() + df["big_move_down"].mean()) * 100

    setups = [
        {
            "name":  "RSI Oversold + Volume Surge + Trending",
            "mask":  (df["rsi"] < 35) & (df["vol_surge"] == True) & (df["is_trending"] == True),
            "bias":  "BUY CE or SELL PE"
        },
        {
            "name":  "RSI Overbought + Volume Surge + Trending",
            "mask":  (df["rsi"] > 65) & (df["vol_surge"] == True) & (df["is_trending"] == True),
            "bias":  "BUY PE or SELL CE"
        },
        {
            "name":  "Above VWAP + EMA Bull + Afternoon",
            "mask":  (df["above_vwap"] == True) & (df["ema_bull"] == True) & (df["is_afternoon"] == True),
            "bias":  "BUY CE"
        },
        {
            "name":  "Below VWAP + EMA Bear + Afternoon",
            "mask":  (df["above_vwap"] == False) & (df["ema_bear"] == True) & (df["is_afternoon"] == True),
            "bias":  "BUY PE"
        },
        {
            "name":  "Consolidating + Volume Surge + RSI 40-60",
            "mask":  (df["move_5min"].abs() <= 3) & (df["vol_surge"] == True) &
                     (df["rsi"] >= 40) & (df["rsi"] <= 60),
            "bias":  "Either direction — wait for breakout"
        },
        {
            "name":  "Morning + At Day Low + RSI < 40",
            "mask":  (df["is_morning"] == True) & (df["dist_from_day_low"] <= 5) & (df["rsi"] < 40),
            "bias":  "BUY CE"
        },
        {
            "name":  "Afternoon (13-15) + Strong 5m move + Trending",
            "mask":  (df["is_afternoon"] == True) & (df["move_5min"].abs() >= 8) &
                     (df["is_trending"] == True),
            "bias":  "Follow the direction of 5m move"
        },
    ]

    print(f"\nBaseline probability: {baseline:.1f}% of ticks precede a 20-point move\n")

    for setup in setups:
        subset = df[setup["mask"]]
        if len(subset) < MIN_SAMPLES:
            print(f"  {setup['name']}: insufficient data ({len(subset)} samples)")
            continue

        bmu   = subset["big_move_up"].mean()    * 100
        bmd   = subset["big_move_down"].mean()   * 100
        total = bmu + bmd
        lift  = total / baseline if baseline > 0 else 1.0
        avg_move = subset["move_in_next_5min"].mean()

        print(f"Setup: {setup['name']}")
        print(f"  Bias         : {setup['bias']}")
        print(f"  Occurrences  : {len(subset):,} ticks")
        print(f"  Big move up  : {bmu:.1f}%")
        print(f"  Big move down: {bmd:.1f}%")
        print(f"  Total        : {total:.1f}% (vs {baseline:.1f}% baseline = {lift:.1f}x lift)")
        print(f"  Avg 5m move  : {avg_move:.2f} points")
        if lift >= 2.0:
            print(f"  ⭐ EXCELLENT — {lift:.1f}x better than random")
        elif lift >= 1.5:
            print(f"  ✅ GOOD — {lift:.1f}x better than random")
        else:
            print(f"  ⚠️  WEAK — only {lift:.1f}x better than random")
        print()


def generate_custom_rules(df: pd.DataFrame):
    """
    Generate concrete trading rules from discovered patterns.
    These can be directly coded into the trading bot.
    """
    print("\n" + "="*60)
    print(" CUSTOM RULES FOR YOUR BOT")
    print(" (Auto-generated from your data)")
    print("="*60)

    rules = []

    # Rule 1 — Best time to trade
    hour_stats = []
    for hour in range(9, 16):
        h_df = df[df["hour"] == hour]
        if len(h_df) < 100:
            continue
        pct = (h_df["big_move_up"].mean() + h_df["big_move_down"].mean()) * 100
        hour_stats.append((hour, pct, len(h_df)))
    hour_stats.sort(key=lambda x: x[1], reverse=True)
    best_hours = [h for h, p, c in hour_stats if p >= hour_stats[0][1] * 0.8]
    rules.append(f"Best trading hours: {', '.join([f'{h}:00-{h+1}:00' for h in best_hours[:3]])}")

    # Rule 2 — RSI threshold
    rsi_up   = df[df["rsi"] < 35]["big_move_up"].mean()   * 100
    rsi_down = df[df["rsi"] > 65]["big_move_down"].mean()  * 100
    baseline = (df["big_move_up"].mean() + df["big_move_down"].mean()) * 100
    if rsi_up > baseline * 1.3:
        rules.append(f"RSI below 35 precedes upward moves {rsi_up:.0f}% of time (baseline {baseline:.0f}%) — take BUY signals")
    if rsi_down > baseline * 1.3:
        rules.append(f"RSI above 65 precedes downward moves {rsi_down:.0f}% of time — take SELL signals")

    # Rule 3 — Volume surge
    vol_df = df[df["vol_surge"] == True]
    if len(vol_df) > MIN_SAMPLES:
        vol_pct = (vol_df["big_move_up"].mean() + vol_df["big_move_down"].mean()) * 100
        if vol_pct > baseline * 1.2:
            rules.append(f"Volume surge increases big move probability to {vol_pct:.0f}% (vs {baseline:.0f}% baseline) — require volume confirmation")

    # Rule 4 — VWAP
    above_df = df[df["above_vwap"] == True]
    below_df = df[df["above_vwap"] == False]
    if len(above_df) > MIN_SAMPLES and len(below_df) > MIN_SAMPLES:
        above_up = above_df["big_move_up"].mean()   * 100
        below_dn = below_df["big_move_down"].mean()  * 100
        rules.append(f"Above VWAP: {above_up:.0f}% chance of upward move — favour BUY CE")
        rules.append(f"Below VWAP: {below_dn:.0f}% chance of downward move — favour BUY PE")

    print("\nAuto-generated trading rules from your data:\n")
    for i, rule in enumerate(rules, 1):
        print(f"{i}. {rule}")

    # Save rules to file
    os.makedirs(REPORT_DIR, exist_ok=True)
    rules_path = f"{REPORT_DIR}/custom_rules_{datetime.now().strftime('%Y%m%d')}.json"
    with open(rules_path, "w") as f:
        json.dump({"generated": datetime.now().isoformat(), "rules": rules}, f, indent=2)
    print(f"\nRules saved to: {rules_path}")


def main():
    print("\n" + "="*60)
    print(" PATTERN DISCOVERY ANALYSIS")
    print(f" Generated: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("="*60)

    # Load data
    df = load_all_ticks()
    if df.empty:
        print("No data to analyze. Run data_collector.py for at least 1 week first.")
        return

    # Convert types
    for col in ["rsi","vwap","atr","adx","move_1min","move_5min","move_15min",
                "move_in_next_1min","move_in_next_5min"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    for col in ["big_move_up","big_move_down","medium_move_up","medium_move_down",
                "above_vwap","ema_bull","ema_bear","is_trending","vol_surge",
                "is_morning","is_midday","is_afternoon","is_bull_candle","is_bear_candle"]:
        if col in df.columns:
            df[col] = df[col].astype(bool)

    # Run all analyses
    basic_stats(df)
    analyze_time_of_day(df)
    analyze_rsi_ranges(df)
    analyze_vwap_position(df)
    analyze_patterns(df)
    analyze_combined_conditions(df)
    discover_best_entry_setups(df)
    generate_custom_rules(df)

    print("\n" + "="*60)
    print(" Analysis complete.")
    print(f" Data files in  : {DATA_DIR}/")
    print(f" Reports in     : {REPORT_DIR}/")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()

