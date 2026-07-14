"""
Detailed trade logger. Writes every trade with full info to a JSON file
for later analysis — pattern name, each indicator score, entry/exit details,
high/low during trade, signal reasoning etc.
"""

import os
import json
from datetime import datetime
from config import Config
from utils.logger import get_logger

log = get_logger("trade_logger")


def _load_all() -> list:
    try:
        if os.path.exists(Config.DETAILED_LOG_PATH):
            with open(Config.DETAILED_LOG_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_all(records: list):
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    with open(Config.DETAILED_LOG_PATH, "w") as f:
        json.dump(records, f, indent=2, default=str)


def log_trade_entry(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    qty: int,
    score: int,
    signal_reason: str,
    pattern_name: str,
    indicator_scores: dict,
    atr: float,
    option_type: str,
    expiry: str,
) -> str:
    """
    Log a trade entry. Returns a trade_id string.
    indicator_scores example:
      {"pattern": 40, "rsi": 15, "vwap": 15, "ema": 10, "volume": 0, "sr": 10}
    """
    trade_id = f"{symbol}_{datetime.now().strftime('%H%M%S')}"
    record = {
        "trade_id":        trade_id,
        "symbol":          symbol,
        "option_type":     option_type,
        "expiry":          expiry,
        "direction":       direction,
        "entry_price":     entry_price,
        "stop_loss":       stop_loss,
        "qty":             qty,
        "atr_at_entry":    round(atr, 2),
        "score":           score,
        "signal_reason":   signal_reason,
        "pattern_name":    pattern_name,
        "indicator_scores": indicator_scores,
        "entry_time":      datetime.now().isoformat(),
        "exit_price":      None,
        "exit_time":       None,
        "exit_reason":     None,
        "pnl_points":      None,
        "pnl_rupees":      None,
        "high_during_trade": entry_price,
        "low_during_trade":  entry_price,
        "sl_adjustments":  [],
        "price_history":   [{"time": datetime.now().strftime("%H:%M:%S"), "price": entry_price}],
        "status":          "OPEN",
    }
    records = _load_all()
    records.append(record)
    _save_all(records)
    log.info(f"Trade logged: {trade_id} | {direction} {symbol} @ {entry_price} | Score {score} | Pattern: {pattern_name}")
    return trade_id


def log_trade_update(trade_id: str, current_price: float, current_sl: float):
    """Update high/low and price history for an open trade."""
    records = _load_all()
    for r in records:
        if r.get("trade_id") == trade_id and r.get("status") == "OPEN":
            r["high_during_trade"] = max(r.get("high_during_trade", current_price), current_price)
            r["low_during_trade"]  = min(r.get("low_during_trade", current_price), current_price)
            r["current_sl"]        = current_sl
            r.setdefault("price_history", []).append({
                "time":  datetime.now().strftime("%H:%M:%S"),
                "price": current_price
            })
            break
    _save_all(records)


def log_sl_adjustment(trade_id: str, old_sl: float, new_sl: float, adjusted_by: str = "system"):
    """Log every SL change — both automatic trails and manual adjustments."""
    records = _load_all()
    for r in records:
        if r.get("trade_id") == trade_id:
            r.setdefault("sl_adjustments", []).append({
                "time":        datetime.now().strftime("%H:%M:%S"),
                "old_sl":      old_sl,
                "new_sl":      new_sl,
                "adjusted_by": adjusted_by,
            })
            r["current_sl"] = new_sl
            break
    _save_all(records)


def log_trade_exit(trade_id: str, exit_price: float, exit_reason: str, pnl_points: float, pnl_rupees: float):
    """Mark trade as closed with full exit details."""
    records = _load_all()
    for r in records:
        if r.get("trade_id") == trade_id and r.get("status") == "OPEN":
            r["exit_price"]   = exit_price
            r["exit_time"]    = datetime.now().isoformat()
            r["exit_reason"]  = exit_reason
            r["pnl_points"]   = round(pnl_points, 2)
            r["pnl_rupees"]   = round(pnl_rupees, 2)
            r["status"]       = "CLOSED"
            # Calculate move from entry to peak/trough
            if r["direction"] == "BUY":
                r["max_profit_pts"] = round(r["high_during_trade"] - r["entry_price"], 2)
                r["captured_pct"]   = round(pnl_points / r["max_profit_pts"] * 100, 1) if r["max_profit_pts"] > 0 else 0
            else:
                r["max_profit_pts"] = round(r["entry_price"] - r["low_during_trade"], 2)
                r["captured_pct"]   = round(pnl_points / r["max_profit_pts"] * 100, 1) if r["max_profit_pts"] > 0 else 0
            break
    _save_all(records)
    log.info(f"Trade closed: {trade_id} | {exit_reason} @ {exit_price} | P&L ₹{pnl_rupees}")


def get_trade_detail(trade_id: str) -> dict:
    """Return full detail for a single trade by ID."""
    for r in _load_all():
        if r.get("trade_id") == trade_id:
            return r
    return {}


def get_today_trades() -> list:
    """Return all trades (open and closed) from today."""
    today = datetime.now().date().isoformat()
    return [r for r in _load_all() if r.get("entry_time", "").startswith(today)]
