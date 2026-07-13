"""
Paper trading engine. Polls live Angel One candles every N seconds,
runs the full signal + risk pipeline, simulates trades, sends Telegram
alerts, and logs everything to CSV. No real orders are placed.
"""

import time
import json
import pandas as pd
from datetime import datetime, timedelta
from config import Config
from broker.angelone_client import AngelOneClient
from strategy.signal_engine import generate_signals
from risk.risk_manager import RiskManager
from notifications.telegram_notifier import (
    notify_entry, notify_exit, notify_signal,
    notify_sl_trail, notify_error, notify_bot_started, notify_bot_stopped,
    notify_daily_limit_hit
)
from utils.logger import get_logger
from utils.heartbeat import write_heartbeat, mark_stopped

log = get_logger("paper_trader")

POLL_SECONDS    = 120
LOOKBACK_CANDLES= 150


class PaperTrader:
    def __init__(self, instruments: list):
        """
        instruments: list of dicts from instrument_selector.select_instruments()
        Each dict must have: symbol, token, exchange, option_type
        """
        self.instruments = instruments
        self.client      = AngelOneClient()
        self.risk        = RiskManager()
        self.positions   = {}   # symbol -> position dict
        self.trades      = []   # completed trades
        self.running     = False

    def _fetch(self, instrument: dict) -> pd.DataFrame:
        to_dt   = datetime.now()
        from_dt = to_dt - timedelta(days=5)
        return self.client.get_candles(
            symbol_token=instrument["token"],
            exchange=instrument["exchange"],
            interval=Config.TIMEFRAME,
            from_date=from_dt.strftime("%Y-%m-%d %H:%M"),
            to_date=to_dt.strftime("%Y-%m-%d %H:%M"),
        ).tail(LOOKBACK_CANDLES).reset_index(drop=True)

    def _check_exits(self, symbol: str, row: pd.Series):
        pos = self.positions.get(symbol)
        if not pos:
            return

        atr       = row.get("atr", pos["atr"])
        cur_price = row["close"]
        old_sl    = pos["sl"]
        new_sl    = self.risk.trail_stop_loss(old_sl, cur_price, atr, pos["direction"])

        if new_sl != old_sl:
            pos["sl"] = new_sl
            notify_sl_trail(symbol, old_sl, new_sl, cur_price)
            log.info(f"[{symbol}] Trail SL: {old_sl} → {new_sl}")

        exit_price, reason = None, None
        if pos["direction"] == "BUY" and row["low"] <= pos["sl"]:
            exit_price, reason = pos["sl"], "TRAIL_SL"
        elif pos["direction"] == "SELL" and row["high"] >= pos["sl"]:
            exit_price, reason = pos["sl"], "TRAIL_SL"

        if self.risk.should_square_off():
            exit_price, reason = cur_price, "SQUARE_OFF"

        if exit_price is not None:
            self._close_position(symbol, exit_price, reason)

    def _close_position(self, symbol: str, exit_price: float, reason: str):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return
        pnl_pts = (exit_price - pos["entry"]) if pos["direction"] == "BUY" \
            else (pos["entry"] - exit_price)
        pnl_rs  = round(pnl_pts * pos["qty"] - 40, 2)  # ₹40 brokerage
        trade   = {**pos, "exit": exit_price, "exit_time": datetime.now(),
                   "pnl_points": round(pnl_pts, 2), "pnl_rupees": pnl_rs, "reason": reason}
        self.trades.append(trade)
        self.risk.record_trade_close(pnl_rs)
        notify_exit(symbol, pos["direction"], pos["entry"], exit_price, pnl_rs, reason)
        log.info(f"[{symbol}] EXIT {reason} @ {exit_price} | P&L ₹{pnl_rs}")

        if self.risk.daily_pnl <= -abs(Config.MAX_LOSS_PER_DAY):
            notify_daily_limit_hit("Daily Loss", self.risk.daily_pnl)

    def _check_entries(self, symbol: str, instrument: dict, row: pd.Series):
        if symbol in self.positions:
            return
        allowed, reason = self.risk.can_trade()
        if not allowed:
            return
        if not row.get("signal"):
            return

        direction = row["signal"]
        score     = row.get("signal_score", 0)
        sig_reason= row.get("signal_reason", "")
        entry     = row["close"]
        atr       = row.get("atr", 50) or 50
        sl        = self.risk.initial_stop_loss(entry, atr, direction)
        qty       = self.risk.calculate_quantity(entry, sl)

        self.positions[symbol] = {
            "symbol":     symbol,
            "direction":  direction,
            "entry":      entry,
            "sl":         sl,
            "atr":        atr,
            "qty":        qty,
            "entry_time": datetime.now(),
            "score":      score,
        }
        self.risk.record_trade_open()
        notify_signal(symbol, direction, score, sig_reason, entry)
        notify_entry(symbol, direction, entry, sl, entry, qty)
        log.info(f"[{symbol}] ENTRY {direction} @ {entry} | SL {sl} | Qty {qty}")

    def save_log(self):
        import os
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        if self.trades:
            pd.DataFrame(self.trades).to_csv(Config.TRADE_LOG_PATH, index=False)
            log.info(f"Saved {len(self.trades)} paper trades → {Config.TRADE_LOG_PATH}")

    def run(self):
        self.client.login()
        self.running = True
        notify_bot_started("PAPER")
        log.info(f"Paper trading started. Monitoring {len(self.instruments)} instruments.")

        try:
            while self.running:
                for inst in self.instruments:
                    symbol = inst["symbol"]
                    try:
                        df = self._fetch(inst)
                        if df.empty:
                            continue
                        df  = generate_signals(df)
                        row = df.iloc[-1]
                        self._check_exits(symbol, row)
                        self._check_entries(symbol, inst, row)
                    except Exception as e:
                        log.error(f"Error processing {symbol}: {e}")
                        notify_error(f"{symbol}: {str(e)[:100]}")

                # Write heartbeat + current state for dashboard
                write_heartbeat({
                    "mode":        "paper",
                    "positions":   list(self.positions.keys()),
                    "trades_today":self.risk.trades_today,
                    "daily_pnl":   self.risk.daily_pnl,
                    "instruments": [i["symbol"] for i in self.instruments],
                })
                time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            self.running = False
            self.save_log()
            mark_stopped()
            notify_bot_stopped("manual stop")
