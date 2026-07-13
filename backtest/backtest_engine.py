"""
Backtest engine. Simulates trading on historical OHLCV data.

Features:
- ATR-based trailing stop loss (same logic as live trading)
- Brokerage deduction (₹20 per order = ₹40 round trip)
- Slippage simulation (assumes 1-2 points adverse fill vs signal price)
- Time filters (respects no-entry windows)
- Daily loss limit and max trades per day
- Walk-forward mode: train on first N% of data, validate on remaining
"""

import os
import pandas as pd
from datetime import datetime, time
from config import Config
from strategy.signal_engine import generate_signals
from risk.risk_manager import RiskManager
from utils.logger import get_logger

log = get_logger("backtest")

BROKERAGE_PER_TRADE = 40   # ₹20 per leg x 2 legs
SLIPPAGE_POINTS     = 1.5  # assumed adverse fill vs signal price


class BacktestEngine:
    def __init__(self, capital=None, walk_forward_split=None):
        """
        capital: starting capital
        walk_forward_split: float 0-1. E.g. 0.7 = train on first 70%, validate on last 30%.
                            None = use all data as one run.
        """
        self.capital            = capital or Config.CAPITAL
        self.walk_forward_split = walk_forward_split
        self.trades             = []

    def _simulate(self, df: pd.DataFrame, label: str = "full") -> list:
        df     = generate_signals(df)
        risk   = RiskManager()
        trades = []
        pos    = None   # current open position

        for i, row in df.iterrows():
            ts       = row.get("timestamp", i)
            candle_t = ts.time() if hasattr(ts, "time") else time(10, 0)
            atr      = row.get("atr", 50) or 50

            # ── Check square-off time ────────────────────────────────────────
            if pos and candle_t >= time(15, 15):
                exit_price = row["close"] - SLIPPAGE_POINTS \
                    if pos["direction"] == "BUY" else row["close"] + SLIPPAGE_POINTS
                trades.append(self._close_trade(pos, exit_price, ts, "SQUARE_OFF"))
                pos = None
                continue

            # ── Update trailing stop loss ────────────────────────────────────
            if pos:
                current_price = row["close"]
                new_sl = risk.trail_stop_loss(pos["sl"], current_price, atr, pos["direction"])
                if new_sl != pos["sl"]:
                    pos["sl"] = new_sl

                # Check if SL or high/low breaches
                if pos["direction"] == "BUY":
                    if row["low"] <= pos["sl"]:
                        trades.append(self._close_trade(pos, pos["sl"] - SLIPPAGE_POINTS, ts, "TRAIL_SL"))
                        pos = None
                        continue
                else:
                    if row["high"] >= pos["sl"]:
                        trades.append(self._close_trade(pos, pos["sl"] + SLIPPAGE_POINTS, ts, "TRAIL_SL"))
                        pos = None
                        continue

            # ── Check for new signal ─────────────────────────────────────────
            if pos is None and row.get("signal") in ("BUY", "SELL"):
                allowed, reason = risk.can_trade()
                if not allowed:
                    continue

                direction  = row["signal"]
                entry      = row["close"]
                entry      = entry + SLIPPAGE_POINTS if direction == "BUY" else entry - SLIPPAGE_POINTS
                sl         = risk.initial_stop_loss(entry, atr, direction)
                qty        = risk.calculate_quantity(entry, sl)

                pos = {
                    "direction":  direction,
                    "entry":      entry,
                    "sl":         sl,
                    "entry_time": ts,
                    "atr":        atr,
                    "qty":        qty,
                    "score":      row.get("signal_score", 0),
                    "reason":     row.get("signal_reason", ""),
                }
                risk.record_trade_open()

        return trades

    def _close_trade(self, pos: dict, exit_price: float, exit_time, reason: str) -> dict:
        direction = pos["direction"]
        entry     = pos["entry"]
        qty       = pos["qty"]
        pnl_pts   = (exit_price - entry) if direction == "BUY" else (entry - exit_price)
        pnl_rs    = round(pnl_pts * qty - BROKERAGE_PER_TRADE, 2)
        return {
            "entry_time":  pos["entry_time"],
            "exit_time":   exit_time,
            "direction":   direction,
            "entry":       round(entry, 2),
            "exit":        round(exit_price, 2),
            "qty":         qty,
            "pnl_points":  round(pnl_pts, 2),
            "pnl_rupees":  pnl_rs,
            "exit_reason": reason,
            "score":       pos.get("score", 0),
            "reason":      pos.get("reason", ""),
        }

    def run(self, df: pd.DataFrame):
        """
        Run backtest. If walk_forward_split set, runs train + validate separately.
        Returns (trades_df, summary_dict) or
                ({"train": trades_df, "validate": trades_df}, {"train":..., "validate":...})
        """
        if self.walk_forward_split:
            split      = int(len(df) * self.walk_forward_split)
            train_df   = df.iloc[:split].reset_index(drop=True)
            val_df     = df.iloc[split:].reset_index(drop=True)
            train_t    = self._simulate(train_df, "train")
            val_t      = self._simulate(val_df,   "validate")
            return (
                {"train": pd.DataFrame(train_t), "validate": pd.DataFrame(val_t)},
                {"train": self._summary(train_t, "TRAIN"),
                 "validate": self._summary(val_t, "VALIDATE")}
            )
        trades = self._simulate(df)
        return pd.DataFrame(trades), self._summary(trades)

    def _summary(self, trades: list, label: str = "") -> dict:
        if not trades:
            return {"label": label, "total_trades": 0, "note": "No signals triggered"}
        df   = pd.DataFrame(trades)
        wins = df[df["pnl_rupees"] > 0]
        loss = df[df["pnl_rupees"] <= 0]
        total_pnl = df["pnl_rupees"].sum()
        return {
            "label":          label,
            "total_trades":   len(df),
            "wins":           len(wins),
            "losses":         len(loss),
            "win_rate_pct":   round(len(wins) / len(df) * 100, 1),
            "total_pnl":      round(total_pnl, 2),
            "avg_win":        round(wins["pnl_rupees"].mean(), 2) if len(wins) else 0,
            "avg_loss":       round(loss["pnl_rupees"].mean(), 2) if len(loss) else 0,
            "best_trade":     round(df["pnl_rupees"].max(), 2),
            "worst_trade":    round(df["pnl_rupees"].min(), 2),
            "final_capital":  round(self.capital + total_pnl, 2),
        }


def run_backtest_from_csv(csv_path: str, walk_forward_split=None):
    """Convenience runner from a CSV file."""
    df     = pd.read_csv(csv_path, parse_dates=["timestamp"])
    engine = BacktestEngine(walk_forward_split=walk_forward_split)
    trades, summary = engine.run(df)

    os.makedirs(Config.LOG_DIR, exist_ok=True)
    if isinstance(trades, dict):
        for k, v in trades.items():
            if not v.empty:
                v.to_csv(f"{Config.LOG_DIR}/backtest_{k}.csv", index=False)
        for k, s in summary.items():
            print(f"\n--- {s.get('label','').upper()} ---")
            for key, val in s.items(): print(f"  {key}: {val}")
    else:
        if not trades.empty:
            trades.to_csv(f"{Config.LOG_DIR}/backtest_trades.csv", index=False)
        print("\n--- Backtest Summary ---")
        for k, v in summary.items(): print(f"  {k}: {v}")

    return trades, summary
