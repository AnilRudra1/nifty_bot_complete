import time
import os
import threading
import pandas as pd
from datetime import datetime, timedelta, time as dtime
from config import Config
from broker.angelone_client import AngelOneClient
from strategy.signal_engine import generate_signals
from risk.risk_manager import RiskManager
from notifications.telegram_notifier import (
    notify_entry, notify_exit, notify_signal,
    notify_sl_trail, notify_error,
    notify_bot_started, notify_bot_stopped,
)
from utils.logger import get_logger
from utils.heartbeat import write_heartbeat, mark_stopped

log = get_logger("paper_trader")


class PaperTrader:
    def __init__(self, instruments: list):
        self.instruments = instruments
        self.client      = AngelOneClient()
        self.risk        = RiskManager()
        self.positions   = {}
        self.trades      = []
        self.running     = False

    def _fetch_candles(self, token, exchange, days=5):
        to_dt   = datetime.now()
        from_dt = to_dt - timedelta(days=days)
        df = self.client.get_candles(
            symbol_token=token,
            exchange=exchange,
            interval=Config.TIMEFRAME,
            from_date=from_dt.strftime("%Y-%m-%d %H:%M"),
            to_date=to_dt.strftime("%Y-%m-%d %H:%M"),
        )
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        return df

    def _check_exit(self, symbol, ltp):
        pos = self.positions.get(symbol)
        if not pos:
            return
        atr    = pos.get("atr", ltp * 0.05) or ltp * 0.05
        old_sl = pos["sl"]
        if pos.get("sl_manual"):
            new_sl = old_sl
        else:
            new_sl = self.risk.trail_stop_loss(old_sl, ltp, pos["entry"], pos["direction"])
        if new_sl != old_sl:
            pos["sl"]         = new_sl
            pos["current_sl"] = new_sl
            pos["sl_manual"]  = False
            phase = self.risk.get_sl_phase(new_sl, pos["entry"], pos["direction"])
            notify_sl_trail(symbol, old_sl, new_sl, ltp)
            log.info(f"[{symbol}] SL: {old_sl} -> {new_sl} | {phase} | Price:{ltp}")
        else:
            pos["current_sl"] = pos["sl"]
        pos["last_price"] = ltp
        pos["high"]       = max(pos.get("high", ltp), ltp)
        pos["low"]        = min(pos.get("low",  ltp), ltp)
        exit_price, reason = None, None
        if pos["direction"] == "BUY" and ltp <= pos["sl"]:
            exit_price, reason = pos["sl"], "TRAIL_SL"
        elif pos["direction"] == "SELL" and ltp >= pos["sl"]:
            exit_price, reason = pos["sl"], "TRAIL_SL"
        if self.risk.should_square_off():
            exit_price, reason = ltp, "SQUARE_OFF"
        if exit_price:
            self._close_position(symbol, exit_price, reason)

    def _close_position(self, symbol, exit_price, reason):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return
        pnl_pts = (exit_price - pos["entry"]) if pos["direction"] == "BUY" \
            else (pos["entry"] - exit_price)
        pnl_rs  = round(pnl_pts * pos["qty"] - 40, 2)
        self.trades.append({
            "symbol":        symbol,
            "direction":     pos["direction"],
            "entry":         pos["entry"],
            "exit":          exit_price,
            "entry_time":    str(pos["entry_time"]),
            "exit_time":     str(datetime.now()),
            "qty":           pos["qty"],
            "pnl_points":    round(pnl_pts, 2),
            "pnl_rupees":    pnl_rs,
            "reason":        reason,
            "high":          pos.get("high", exit_price),
            "low":           pos.get("low",  exit_price),
            "score":         pos.get("score", 0),
            "pattern":       pos.get("pattern", ""),
            "signal_reason": pos.get("signal_reason", ""),
        })
        self.risk.record_trade_close(pnl_rs)
        notify_exit(symbol, pos["direction"], pos["entry"], exit_price, pnl_rs, reason)
        log.info(f"[{symbol}] EXIT {reason} @ {exit_price} | P&L Rs.{pnl_rs}")
        self.save_log()

    def _check_entry(self, inst, df):
        symbol = inst["symbol"]
        if symbol in self.positions:
            return
        allowed, reason = self.risk.can_trade()
        if not allowed:
            return
        row    = df.iloc[-1]
        signal = row.get("signal")
        if not signal or str(signal) == "nan" or signal not in ("BUY", "SELL"):
            return
        score      = int(row.get("signal_score", 0))
        sig_reason = str(row.get("signal_reason", ""))
        price      = float(row["close"])
        if price < Config.MIN_PREMIUM:
            log.info(f"[{symbol}] Dead stock Rs.{price}")
            return
        if self.risk.is_expiry_day() and datetime.now().hour >= Config.EXPIRY_CUTOFF_HOUR:
            log.info(f"[{symbol}] Expiry cutoff")
            return
        atr     = float(row.get("atr", price * 0.05) or price * 0.05)
        sl      = self.risk.initial_stop_loss(price, signal)
        qty     = Config.LOT_SIZE * Config.FIXED_LOTS
        pattern = ""
        for col in row.index:
            if col.startswith("pat_") and row.get(col):
                pattern = col.replace("pat_", "").replace("_", " ").title()
                break
        self.positions[symbol] = {
            "symbol":        symbol,
            "direction":     signal,
            "entry":         price,
            "sl":            sl,
            "current_sl":    sl,
            "sl_manual":     False,
            "atr":           atr,
            "qty":           qty,
            "entry_time":    datetime.now(),
            "score":         score,
            "pattern":       pattern,
            "signal_reason": sig_reason,
            "high":          price,
            "low":           price,
            "last_price":    price,
            "token":         inst.get("token", ""),
            "exchange":      inst.get("exchange", "NFO"),
        }
        self.risk.record_trade_open()
        notify_signal(symbol, signal, score, sig_reason, price)
        notify_entry(symbol, signal, price, sl, price, qty)
        log.info(
            f"[{symbol}] ENTRY {signal} @ {price} | "
            f"SL {sl} | Qty {qty} | Score {score} | Pattern:{pattern}"
        )

    def _ltp_exit_loop(self):
        while self.running:
            for sym in list(self.positions.keys()):
                pos      = self.positions.get(sym)
                if not pos:
                    continue
                token    = pos.get("token", "")
                exchange = pos.get("exchange", "NFO")
                if not token:
                    continue
                try:
                    ltp = self.client.get_ltp(exchange, sym, token)
                    if ltp and ltp > 0:
                        self._check_exit(sym, ltp)
                        pnl = round(
                            (ltp - pos["entry"]) * pos["qty"]
                            if pos["direction"] == "BUY"
                            else (pos["entry"] - ltp) * pos["qty"], 0
                        )
                        log.info(
                            f"[{sym}] LTP:{ltp} | "
                            f"SL:{pos.get('current_sl', 0):.2f} | "
                            f"P&L:Rs.{pnl}"
                        )
                except Exception as e:
                    log.error(f"LTP [{sym}]: {e}")
                time.sleep(2)
            time.sleep(13)

    def adjust_sl(self, symbol, new_sl):
        pos = self.positions.get(symbol)
        if not pos:
            return False, f"{symbol} not found"
        cur = pos.get("last_price", pos["entry"])
        if new_sl <= 0:
            return False, "SL must be > 0"
        if pos["direction"] == "BUY" and new_sl >= cur:
            return False, f"BUY SL must be below Rs.{cur}"
        if pos["direction"] == "SELL" and new_sl <= cur:
            return False, f"SELL SL must be above Rs.{cur}"
        old = pos["sl"]
        pos["sl"] = pos["current_sl"] = new_sl
        pos["sl_manual"] = True
        log.info(f"[{symbol}] Manual SL: {old} -> {new_sl}")
        return True, f"SL updated {old} -> {new_sl}"

    def save_log(self):
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        if self.trades:
            pd.DataFrame(self.trades).to_csv(Config.TRADE_LOG_PATH, index=False)

    def _write_state(self):
        positions_state = {}
        for sym, pos in self.positions.items():
            positions_state[sym] = {
                k: str(v) if isinstance(v, datetime) else v
                for k, v in pos.items()
            }
        write_heartbeat({
            "mode":         "paper",
            "positions":    positions_state,
            "trades_today": self.risk.trades_today,
            "daily_pnl":    self.risk.daily_pnl,
            "instruments":  [i["symbol"] for i in self.instruments],
            "market_dir":   "ORIGINAL",
        })

    def run(self):
        self.client.login()
        self.running = True
        notify_bot_started("PAPER")
        log.info(f"Bot started. Scanning {len(self.instruments)} instruments.")
        log.info("Strategy: original — direct option pattern scanning, no trend filter")

        ltp_thread = threading.Thread(target=self._ltp_exit_loop, daemon=True)
        ltp_thread.start()

        idx = 0
        try:
            while self.running:
                inst   = self.instruments[idx % len(self.instruments)]
                symbol = inst["symbol"]
                token  = inst.get("token", "")

                if not token:
                    idx += 1
                    continue

                try:
                    df = self._fetch_candles(token, inst["exchange"], days=3)
                    if df.empty:
                        log.warning(f"[{symbol}] No data")
                    else:
                        df  = generate_signals(df)
                        row = df.iloc[-1]
                        log.info(
                            f"[{symbol}] "
                            f"Price:{row['close']} | "
                            f"Signal:{row.get('signal', 'none')} | "
                            f"Score:{row.get('signal_score', 0)}"
                        )
                        if symbol in self.positions:
                            self._check_exit(symbol, float(row["close"]))
                        self._check_entry(inst, df)
                except Exception as e:
                    log.error(f"Scan [{symbol}]: {e}")

                self._write_state()
                idx += 1
                time.sleep(Config.API_DELAY)

        except KeyboardInterrupt:
            log.info("Stopped by user")
        except Exception as e:
            log.error(f"Bot crashed: {e}")
            notify_error(f"Bot crashed: {e}")
        finally:
            self.running = False
            self.save_log()
            mark_stopped()
            notify_bot_stopped("stopped")
