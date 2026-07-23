"""
Quick daily report — compact output easy to copy paste.
Run: python3 quick_report.py
"""
import os
import pandas as pd
from datetime import datetime

TRADE_FILE = "logs/trades.csv"

if not os.path.exists(TRADE_FILE):
    print("No trades file found")
    exit()

df = pd.read_csv(TRADE_FILE)
df["exit_time"]  = pd.to_datetime(df["exit_time"],  errors="coerce")
df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
df["pnl_rupees"] = pd.to_numeric(df["pnl_rupees"],  errors="coerce").fillna(0)
df["entry"]      = pd.to_numeric(df["entry"],        errors="coerce").fillna(0)
df["exit"]       = pd.to_numeric(df["exit"],         errors="coerce").fillna(0)
df["high"]       = pd.to_numeric(df["high"],         errors="coerce").fillna(0)
df["low"]        = pd.to_numeric(df["low"],          errors="coerce").fillna(0)
df["score"]      = pd.to_numeric(df["score"],        errors="coerce").fillna(0)

today = datetime.now().date()
df    = df[df["exit_time"].dt.date == today]

if df.empty:
    print("No trades today")
    exit()

wins   = df[df["pnl_rupees"] > 0]
losses = df[df["pnl_rupees"] <= 0]
total  = df["pnl_rupees"].sum()

# ── Header ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f" {today.strftime('%d %b %Y')} | "
      f"Trades:{len(df)} W:{len(wins)} L:{len(losses)} "
      f"WR:{round(len(wins)/len(df)*100,1)}% | "
      f"P&L:Rs.{total:,.0f}")
print(f"{'='*65}")

# ── Trades ─────────────────────────────────────────────────────────────────────
print(f"\n{'R':<2} {'Symbol':<22} {'D':<2} {'En':>6} {'Ex':>6} {'Hi':>6} {'Lo':>6} {'P&L':>8} {'Sc':>3} {'Pattern':<16} {'In':<6} {'Out':<6}")
print("-"*105)

for _, r in df.sort_values("entry_time").iterrows():
    flag    = "✅" if r["pnl_rupees"] > 0 else "❌"
    sym     = str(r.get("symbol",""))[-16:]
    dir_    = str(r.get("direction",""))[:1]
    pat     = str(r.get("pattern","—"))[:15]
    reason  = str(r.get("reason",""))[:4]
    et      = r["entry_time"].strftime("%H:%M") if pd.notna(r["entry_time"]) else "--:--"
    xt      = r["exit_time"].strftime("%H:%M")  if pd.notna(r["exit_time"])  else "--:--"
    print(f"{flag} {sym:<22} {dir_:<2} {r['entry']:>6.1f} {r['exit']:>6.1f} "
          f"{r['high']:>6.1f} {r['low']:>6.1f} {r['pnl_rupees']:>8.0f} "
          f"{int(r['score']):>3} {pat:<16} {et:<6} {xt:<6}")

# ── Pattern summary ────────────────────────────────────────────────────────────
print(f"\nPATTERN     Tr  W  L    P&L")
print("-"*35)
for pat, g in df.groupby("pattern"):
    if not pat or str(pat) == "nan": continue
    w = len(g[g["pnl_rupees"]>0])
    l = len(g[g["pnl_rupees"]<=0])
    print(f"{str(pat)[:12]:<12} {len(g):>2} {w:>2} {l:>2} {g['pnl_rupees'].sum():>8.0f}")

# ── Time summary ───────────────────────────────────────────────────────────────
print(f"\nTIME       Tr  W  L    P&L")
print("-"*30)
df["slot"] = df["entry_time"].dt.hour.astype(str) + "h"
for slot, g in df.groupby("slot"):
    w = len(g[g["pnl_rupees"]>0])
    l = len(g[g["pnl_rupees"]<=0])
    print(f"{slot:<10} {len(g):>2} {w:>2} {l:>2} {g['pnl_rupees'].sum():>8.0f}")

# ── Score summary ──────────────────────────────────────────────────────────────
print(f"\nSCORE      Tr  W  L    P&L")
print("-"*30)
df["band"] = pd.cut(df["score"], bins=[0,59,69,79,200],
                    labels=["50-59","60-69","70-79","80+"])
for band, g in df.groupby("band", observed=True):
    w = len(g[g["pnl_rupees"]>0])
    l = len(g[g["pnl_rupees"]<=0])
    print(f"{str(band):<10} {len(g):>2} {w:>2} {l:>2} {g['pnl_rupees'].sum():>8.0f}")

# ── Footer ─────────────────────────────────────────────────────────────────────
print(f"\nBest:{df['pnl_rupees'].max():,.0f} | "
      f"Worst:{df['pnl_rupees'].min():,.0f} | "
      f"AvgW:{wins['pnl_rupees'].mean():,.0f} | "
      f"AvgL:{losses['pnl_rupees'].mean():,.0f}")
print(f"{'✅ PROFIT' if total>0 else '❌ LOSS'} Rs.{total:,.0f} | "
      f"Brok:Rs.{len(df)*40} | "
      f"Net:Rs.{total-len(df)*40:,.0f}")
print(f"{'='*65}\n")
