"""
Daily trading analysis script.
Run after market close: python3 analyze_today.py
"""

import os
import pandas as pd
from datetime import datetime

print("\n" + "="*70)
print(" NIFTY BOT — DAILY ANALYSIS REPORT")
print(f" Date: {datetime.now().strftime('%d %b %Y')}")
print("="*70)

TRADE_FILE = "logs/trades.csv"

if not os.path.exists(TRADE_FILE):
    print("\n No trades.csv found.")
    exit()

df = pd.read_csv(TRADE_FILE)
if df.empty:
    print("\n No trades recorded.")
    exit()

# Parse times
df["exit_time"]  = pd.to_datetime(df["exit_time"],  errors="coerce")
df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")

# Filter today
today = datetime.now().date()
df    = df[df["exit_time"].dt.date == today]

if df.empty:
    print("\n No trades exited today.")
    exit()

# Numeric columns
for col in ["pnl_rupees","pnl_points","entry","exit","high","low","score","qty"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# Fill missing columns
for col in ["pattern","signal_reason","nifty_signal","confirmation"]:
    if col not in df.columns:
        df[col] = ""

wins   = df[df["pnl_rupees"] > 0]
losses = df[df["pnl_rupees"] <= 0]
total  = df["pnl_rupees"].sum()

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"""
SUMMARY
-------
Total trades    : {len(df)}
Wins            : {len(wins)}
Losses          : {len(losses)}
Win rate        : {round(len(wins)/len(df)*100, 1)}%
Net P&L         : Rs.{round(total, 2):,.2f}
Brokerage paid  : Rs.{len(df)*40} ({len(df)} trades x Rs.40)
Avg win         : Rs.{round(wins['pnl_rupees'].mean(), 2) if len(wins) else 0:,.2f}
Avg loss        : Rs.{round(losses['pnl_rupees'].mean(), 2) if len(losses) else 0:,.2f}
Best trade      : Rs.{round(df['pnl_rupees'].max(), 2):,.2f}
Worst trade     : Rs.{round(df['pnl_rupees'].min(), 2):,.2f}
""")

# ── All trades with entry/exit time and pattern ───────────────────────────────
print("ALL TRADES")
print("-"*110)
print(f"{'#':<3} {'Symbol':<26} {'Dir':<5} {'Entry':>7} {'Exit':>7} {'High':>7} {'Low':>7} {'P&L':>9} {'Sc':>4} {'Pattern':<22} {'Entry Time':<10} {'Exit Time':<10} {'Reason'}")
print("-"*110)

for i, (_, row) in enumerate(df.sort_values("entry_time").iterrows(), 1):
    sym      = str(row.get("symbol",""))[:25]
    dir_     = str(row.get("direction","BUY"))
    entry    = row["entry"]
    exit_    = row["exit"]
    high     = row["high"]
    low      = row["low"]
    pnl      = row["pnl_rupees"]
    score    = int(row["score"])
    pattern  = str(row.get("pattern","—"))[:21]
    reason   = str(row.get("reason",""))[:12]
    flag     = "✅" if pnl > 0 else "❌"

    entry_t  = row["entry_time"].strftime("%H:%M:%S") if pd.notna(row["entry_time"]) else "—"
    exit_t   = row["exit_time"].strftime("%H:%M:%S")  if pd.notna(row["exit_time"])  else "—"

    print(f"{flag} {i:<2} {sym:<26} {dir_:<5} {entry:>7.2f} {exit_:>7.2f} {high:>7.2f} {low:>7.2f} {pnl:>9.2f} {score:>4} {pattern:<22} {entry_t:<10} {exit_t:<10} {reason}")

# ── Detailed trade breakdown ───────────────────────────────────────────────────
print("\nDETAILED TRADE INFO")
print("-"*70)
for i, (_, row) in enumerate(df.sort_values("entry_time").iterrows(), 1):
    pnl     = row["pnl_rupees"]
    flag    = "✅ WIN" if pnl > 0 else "❌ LOSS"
    entry_t = row["entry_time"].strftime("%H:%M:%S") if pd.notna(row["entry_time"]) else "—"
    exit_t  = row["exit_time"].strftime("%H:%M:%S")  if pd.notna(row["exit_time"])  else "—"
    held    = ""
    if pd.notna(row["entry_time"]) and pd.notna(row["exit_time"]):
        mins = int((row["exit_time"] - row["entry_time"]).total_seconds() / 60)
        held = f"{mins} min"

    print(f"\nTrade {i}: {row.get('symbol','—')} — {flag}")
    print(f"  Direction  : {row.get('direction','—')}")
    print(f"  Pattern    : {row.get('pattern','—')}")
    print(f"  Signal why : {row.get('signal_reason','—')}")
    print(f"  Entry      : Rs.{row['entry']:.2f} at {entry_t}")
    print(f"  Exit       : Rs.{row['exit']:.2f} at {exit_t}")
    print(f"  Held for   : {held}")
    print(f"  High/Low   : Rs.{row['high']:.2f} / Rs.{row['low']:.2f}")
    print(f"  Score      : {int(row['score'])}")
    print(f"  P&L        : Rs.{pnl:.2f}")
    print(f"  Exit reason: {row.get('reason','—')}")

# ── Peak analysis ──────────────────────────────────────────────────────────────
print("\nPEAK ANALYSIS")
print("-"*80)
print(f"{'Symbol':<26} {'Dir':<5} {'Entry':>7} {'Peak':>7} {'Exit':>7} {'Available':>10} {'Got':>9} {'Missed':>9}")
print("-"*80)

total_avail = total_got = 0
for _, row in df.sort_values("pnl_rupees", ascending=False).iterrows():
    dir_   = row.get("direction","BUY")
    entry  = row["entry"]
    exit_  = row["exit"]
    high   = row["high"]
    low    = row["low"]
    qty    = int(row.get("qty", 130))
    sym    = str(row.get("symbol",""))[:25]

    if dir_ == "BUY":
        peak      = high
        available = round((peak - entry) * qty, 2)
    else:
        peak      = low
        available = round((entry - peak) * qty, 2)

    got    = row["pnl_rupees"]
    missed = round(available - got, 2)
    total_avail += max(available, 0)
    total_got   += got

    print(f"{sym:<26} {dir_:<5} {entry:>7.2f} {peak:>7.2f} {exit_:>7.2f} {available:>10.2f} {got:>9.2f} {missed:>9.2f}")

print("-"*80)
eff = round(total_got / total_avail * 100, 1) if total_avail > 0 else 0
print(f"{'TOTAL':<26} {'':>5} {'':>7} {'':>7} {'':>7} {total_avail:>10.2f} {total_got:>9.2f} {total_avail-total_got:>9.2f}")
print(f"\nEfficiency: {eff}% of available profit captured")

# ── Exit reasons ───────────────────────────────────────────────────────────────
print("\nEXIT REASON BREAKDOWN")
print("-"*50)
for reason, grp in df.groupby("reason"):
    w = len(grp[grp["pnl_rupees"] > 0])
    l = len(grp[grp["pnl_rupees"] <= 0])
    p = grp["pnl_rupees"].sum()
    print(f"{reason:<15} {len(grp):>3} trades | {w}W {l}L | Rs.{p:,.2f}")

# ── Pattern breakdown ──────────────────────────────────────────────────────────
if df["pattern"].any():
    print("\nPATTERN BREAKDOWN")
    print("-"*50)
    for pat, grp in df.groupby("pattern"):
        if not pat or str(pat) == "nan":
            continue
        w = len(grp[grp["pnl_rupees"] > 0])
        l = len(grp[grp["pnl_rupees"] <= 0])
        p = grp["pnl_rupees"].sum()
        print(f"{str(pat)[:25]:<25} {len(grp):>3} trades | {w}W {l}L | Rs.{p:,.2f}")

# ── Time analysis ──────────────────────────────────────────────────────────────
print("\nTIME OF DAY ANALYSIS")
print("-"*50)
df["entry_hour"] = df["entry_time"].dt.strftime("%H:%M")
df["hour_slot"]  = df["entry_time"].dt.hour.astype(str) + ":00"
for slot, grp in df.groupby("hour_slot"):
    w = len(grp[grp["pnl_rupees"] > 0])
    l = len(grp[grp["pnl_rupees"] <= 0])
    p = grp["pnl_rupees"].sum()
    print(f"{slot} - {int(slot.split(':')[0])+1}:00  {len(grp):>3} trades | {w}W {l}L | Rs.{p:,.2f}")

# ── Score analysis ─────────────────────────────────────────────────────────────
print("\nSIGNAL SCORE ANALYSIS")
print("-"*50)
high_q = df[df["score"] >= 65]
low_q  = df[df["score"] < 65]
if len(high_q):
    hw = len(high_q[high_q["pnl_rupees"] > 0])
    print(f"Score >= 65: {len(high_q):>3} trades | {hw}W {len(high_q)-hw}L | Rs.{high_q['pnl_rupees'].sum():,.2f}")
if len(low_q):
    lw = len(low_q[low_q["pnl_rupees"] > 0])
    print(f"Score <  65: {len(low_q):>3} trades | {lw}W {len(low_q)-lw}L | Rs.{low_q['pnl_rupees'].sum():,.2f}")

# ── Final verdict ──────────────────────────────────────────────────────────────
print("\n" + "="*70)
if total > 0:
    print(f" ✅ PROFITABLE DAY — Net Rs.{total:,.2f}")
elif total == 0:
    print(f" 🔁 BREAKEVEN DAY")
else:
    print(f" ❌ LOSS DAY — Net Rs.{total:,.2f}")
print(f" Trades:{len(df)} | Wins:{len(wins)} | Losses:{len(losses)} | Win rate:{round(len(wins)/len(df)*100,1)}% | Efficiency:{eff}%")
print("="*70 + "\n")
