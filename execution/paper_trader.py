"""
Paper trading engine.

Key design:
- Reads NIFTY SPOT candles to generate directional signals
- BUY signal on Nifty  → enter best CE option (Nifty going UP)
- SELL signal on Nifty → enter best PE option (Nifty going DOWN)
- Exits tracked via option premium price (trailing SL on premium)
- Live LTP exposed via /api/ltp for dashboard real-time updates
- Manual SL adjustment supported via dashboard Adjust SL button
- Dead stock filter skips options with premium below Config.MIN_PREMIUM
- No trade limits or daily loss limits (testing mode)
"""

import time
import os
import pandas as pd
from datetime import datetime, timedelta, time as dtime
from config import Config
from broker.angelone_client import AngelOneClient
from strategy.signal_engine import generate_signals, get_market_direction
from strategy.indicators import add_all_indicators
from risk.risk_manager import RiskManager
from notifications.telegram_notifier import (
    notify_entry, notify_exit, notify_signal,
    notify_sl_trail, notify_error,
    notify_bot_started, notify_bot_stopped,
)
from utils.logger import get_logger
from utils.heartbeat import write_heartbeat, mark_stopped

log = get_logger("paper_trader")

# ── Constants ─────────────────────────────────────────────────────────────────
NIFTY_SPOT_TOKEN  = "99926000"
NIFTY_SPOT_SYMBOL = "Nifty 50"
NIFTY_EXCHANGE    = "NSE"


class PaperTrader:
    def __init__(self, instruments: list):
        """
        instruments: list of dicts from instrument_selector.
        Each dict has: symbol, token, exchange, strike, option_type, score, expiry
        """
        self.instruments       = instruments
        self.client            = AngelOneClient()
        self.risk              = RiskManager()
        self.positions         = {}   # symbol → position dict
        self.trades            = []   # completed trades
        self.running           = False
        self._market_dir       = "NEUTRAL"
        self._dir_checked      = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fetch_candles(self, token: str, exchange: str, days: int = 5) -> pd.DataFrame:
        """Fetch OHLCV candles and strip timezone."""
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

    def _is_dead_stock(self, price: float, symbol: str) -> tuple:
        """
        Returns (True, reason) if this option should be skipped.
        Dead stock = near-zero premium or expiry day after cutoff hour.
        """
        if price < Config.MIN_PREMIUM:
            return True, f"Premium ₹{price} below ₹{Config.MIN_PREMIUM} minimum"
        if self.risk.is_expiry_day() and datetime.now().hour >= Config.EXPIRY_CUTOFF_HOUR:
            return True, f"Expiry day no-trade after {Config.EXPIRY_CUTOFF_HOUR}:00"
        return False, ""

    def _detect_market_direction(self):
        """Detect Nifty trend direction once after 9:45 AM."""
        try:
            df = self._fetch_candles(NIFTY_SPOT_TOKEN, NIFTY_EXCHANGE, days=1)
            if not df.empty:
                df = add_all_indicators(df)
                self._market_dir  = get_market_direction(df)
                self._dir_checked = True
                log.info(f"Market direction: {self._market_dir}")
        except Exception as e:
            log.warning(f"Direction check failed: {e}")

    # ── Exit logic ────────────────────────────────────────────────────────────

    def _check_exits(self, symbol: str, row: pd.Series):
        pos = self.positions.get(symbol)
        if not pos:
            return

        cur_price = float(row.get("close", pos["entry"]))
        atr       = float(row.get("atr", pos["atr"]) or pos["atr"])

        # Track high/low during trade
        pos["high"]       = max(pos.get("high", cur_price), cur_price)
        pos["low"]        = min(pos.get("low", cur_price), cur_price)
        pos["last_price"] = cur_price

        old_sl = pos["sl"]

        # Only auto-trail if SL was not manually set
        if pos.get("sl_manual"):
            new_sl = old_sl
        else:
            new_sl = self.risk.trail_stop_loss(old_sl, cur_price, atr, pos["direction"])

        if new_sl != old_sl:
            pos["sl"]         = new_sl
            pos["current_sl"] = new_sl
            pos["sl_manual"]  = False
            notify_sl_trail(symbol, old_sl, new_sl, cur_price)
            log.info(f"[{symbol}] Trail SL: {old_sl} → {new_sl}")
        else:
            pos["current_sl"] = pos["sl"]

        # Check exit conditions
        exit_price, reason = None, None

        if pos["direction"] == "BUY":
            if row.get("low", cur_price) <= pos["sl"]:
                exit_price, reason = pos["sl"], "TRAIL_SL"
        else:
            if row.get("high", cur_price) >= pos["sl"]:
                exit_price, reason = pos["sl"], "TRAIL_SL"

        if self.risk.should_square_off():
            exit_price, reason = cur_price, "SQUARE_OFF"

        if exit_price is not None:
            self._close_position(symbol, exit_price, reason)

    def _close_position(self, symbol: str, exit_price: float, reason: str):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return

        pnl_pts = (
            (exit_price - pos["entry"])
            if pos["direction"] == "BUY"
            else (pos["entry"] - exit_price)
        )
        pnl_rs = round(pnl_pts * pos["qty"] - 40, 2)

        trade = {
            "symbol":      symbol,
            "direction":   pos["direction"],
            "entry":       pos["entry"],
            "exit":        exit_price,
            "entry_time":  str(pos["entry_time"]),
            "exit_time":   str(datetime.now()),
            "qty":         pos["qty"],
            "pnl_points":  round(pnl_pts, 2),
            "pnl_rupees":  pnl_rs,
            "reason":      reason,
            "high":        pos.get("high", exit_price),
            "low":         pos.get("low", exit_price),
            "score":       pos.get("score", 0),
            "pattern":     pos.get("pattern", ""),
            "signal_reason": pos.get("signal_reason", ""),
        }
        self.trades.append(trade)
        self.risk.record_trade_close(pnl_rs)
        notify_exit(symbol, pos["direction"], pos["entry"], exit_price, pnl_rs, reason)
        log.info(f"[{symbol}] EXIT {reason} @ {exit_price} | P&L ₹{pnl_rs}")
        self.save_log()

    # ── Entry logic ───────────────────────────────────────────────────────────

    def _try_enter(self, inst: dict, nifty_signal: str, score: int, reason: str):
        """
        Try to enter a position on a specific option instrument.
        nifty_signal is the direction on Nifty spot ('BUY' or 'SELL').
        For CE options we enter on BUY signal.
        For PE options we enter on SELL signal.
        The entry direction stored is always BUY (we are buying the option).
        """
        symbol = inst["symbol"]

        if symbol in self.positions:
            return

        allowed, block_reason = self.risk.can_trade()
        if not allowed:
            log.info(f"[{symbol}] Blocked: {block_reason}")
            return

        # Fetch latest option price
        try:
            opt_df = self._fetch_candles(inst["token"], inst["exchange"], days=3)
            if opt_df.empty:
                log.warning(f"[{symbol}] No option data")
                return
        except Exception as e:
            log.error(f"[{symbol}] Fetch error: {e}")
            return

        opt_row   = opt_df.iloc[-1]
        opt_price = float(opt_row["close"])

        # Dead stock filter
        dead, dead_reason = self._is_dead_stock(opt_price, symbol)
        if dead:
            log.info(f"[{symbol}] Dead stock: {dead_reason}")
            return

        atr = float(opt_row.get("atr", opt_price * 0.05) or opt_price * 0.05)
        # For buying options, SL is below entry (if option drops we exit)
        sl  = self.risk.initial_stop_loss(opt_price, atr, "BUY")
        qty = Config.LOT_SIZE * Config.FIXED_LOTS

        # Find pattern name from Nifty signal reason
        pattern = reason.split(",")[0].strip() if reason else "Signal"

        self.positions[symbol] = {
            "symbol":        symbol,
            "direction":     "BUY",    # we always BUY the option
            "nifty_signal":  nifty_signal,
            "option_type":   inst.get("option_type", "CE"),
            "entry":         opt_price,
            "sl":            sl,
            "current_sl":    sl,
            "sl_manual":     False,
            "atr":           atr,
            "qty":           qty,
            "entry_time":    datetime.now(),
            "score":         score,
            "pattern":       pattern,
            "signal_reason": reason,
            "high":          opt_price,
            "low":           opt_price,
            "last_price":    opt_price,
        }
        self.risk.record_trade_open()

        notify_signal(symbol, "BUY", score, reason, opt_price)
        notify_entry(symbol, "BUY", opt_price, sl, opt_price, qty)
        log.info(
            f"[{symbol}] ENTRY BUY @ {opt_price} | SL {sl} | "
            f"Qty {qty} | Nifty:{nifty_signal} | Score:{score} | {reason}"
        )

    # ── Manual SL adjustment (called from dashboard) ───────────────────────────

    def adjust_sl(self, symbol: str, new_sl: float) -> tuple:
        """Validate and apply a manual SL adjustment."""
        pos = self.positions.get(symbol)
        if not pos:
            return False, f"{symbol} not in open positions"

        cur_price = pos.get("last_price", pos["entry"])
        direction = pos["direction"]
        old_sl    = pos["sl"]

        # Validate
        if new_sl <= 0:
            return False, "SL must be greater than 0"
        if direction == "BUY" and new_sl >= cur_price:
            return False, f"BUY SL must be below live price ₹{cur_price}"
        if direction == "SELL" and new_sl <= cur_price:
            return False, f"SELL SL must be above live price ₹{cur_price}"

        pos["sl"]        = new_sl
        pos["current_sl"] = new_sl
        pos["sl_manual"] = True
        log.info(f"[{symbol}] Manual SL: {old_sl} → {new_sl}")
        return True, f"SL updated {old_sl} → {new_sl}"

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_log(self):
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        if self.trades:
            pd.DataFrame(self.trades).to_csv(Config.TRADE_LOG_PATH, index=False)

    # ── Heartbeat state for dashboard ─────────────────────────────────────────

    def _write_state(self):
        positions_state = {}
        for sym, pos in self.positions.items():
            positions_state[sym] = {
                "symbol":      sym,
                "direction":   pos.get("direction", "BUY"),
                "nifty_signal": pos.get("nifty_signal", ""),
                "option_type": pos.get("option_type", ""),
                "entry":       pos.get("entry", 0),
                "sl":          pos.get("sl", 0),
                "current_sl":  pos.get("current_sl", pos.get("sl", 0)),
                "qty":         pos.get("qty", 0),
                "entry_time":  str(pos.get("entry_time", "")),
                "score":       pos.get("score", 0),
                "pattern":     pos.get("pattern", ""),
                "high":        pos.get("high", pos.get("entry", 0)),
                "low":         pos.get("low", pos.get("entry", 0)),
                "last_price":  pos.get("last_price", pos.get("entry", 0)),
                "token":       next(
                    (i["token"] for i in self.instruments if i["symbol"] == sym), ""
                ),
                "exchange":    next(
                    (i["exchange"] for i in self.instruments if i["symbol"] == sym), "NFO"
                ),
            }
        write_heartbeat({
            "mode":          "paper",
            "positions":     positions_state,
            "trades_today":  self.risk.trades_today,
            "daily_pnl":     self.risk.daily_pnl,
            "instruments":   [i["symbol"] for i in self.instruments],
            "market_dir":    self._market_dir,
        })

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        self.client.login()
        self.running = True
        notify_bot_started("PAPER")
        log.info(f"Paper trading started. Monitoring {len(self.instruments)} instruments.")
        log.info(f"Instruments: {[i['symbol'] for i in self.instruments]}")

        try:
            while self.running:

                # ── Detect market direction once after 9:45 AM ──────────────
                if not self._dir_checked and datetime.now().time() >= dtime(9, 45):
                    self._detect_market_direction()
                    time.sleep(3)

                # ── Step 1: Read Nifty spot for signal ──────────────────────
                try:
                    nifty_df = self._fetch_candles(NIFTY_SPOT_TOKEN, NIFTY_EXCHANGE, days=3)

                    if nifty_df.empty:
                        log.warning("Nifty spot data empty, waiting...")
                        time.sleep(Config.API_DELAY)
                        continue

                    nifty_df      = generate_signals(nifty_df)
                    nifty_row     = nifty_df.iloc[-1]
                    nifty_signal  = nifty_row.get("signal")
                    nifty_score   = int(nifty_row.get("signal_score", 0))
                    nifty_reason  = str(nifty_row.get("signal_reason", ""))
                    nifty_close   = float(nifty_row["close"])

                    log.info(
                        f"Nifty @ {nifty_close} | "
                        f"Signal: {nifty_signal or '—'} | "
                        f"Score: {nifty_score} | "
                        f"Dir: {self._market_dir} | "
                        f"{nifty_reason}"
                    )
                except Exception as e:
                    log.error(f"Nifty fetch error: {e}")
                    time.sleep(Config.API_DELAY)
                    continue

                time.sleep(3)  # small pause after Nifty fetch

                # ── Step 2: Check exits on all open positions ────────────────
                for sym in list(self.positions.keys()):
                    pos  = self.positions.get(sym)
                    inst = next((i for i in self.instruments if i["symbol"] == sym), None)
                    if not inst or not pos:
                        continue
                    try:
                        opt_df = self._fetch_candles(inst["token"], inst["exchange"], days=1)
                        if not opt_df.empty:
                            self._check_exits(sym, opt_df.iloc[-1])
                    except Exception as e:
                        log.error(f"Exit check error [{sym}]: {e}")
                    time.sleep(Config.API_DELAY)

                # ── Step 3: Enter new trade if signal exists ─────────────────
                if nifty_signal in ("BUY", "SELL") and nifty_score >= Config.SIGNAL_SCORE_MIN:
                    # BUY signal on Nifty  → buy a CE (CE gains when Nifty rises)
                    # SELL signal on Nifty → buy a PE (PE gains when Nifty falls)
                    target_type = "CE" if nifty_signal == "BUY" else "PE"

                    candidates = [
                        i for i in self.instruments
                        if i.get("option_type", "").upper() == target_type
                        and i["symbol"] not in self.positions
                    ]

                    if not candidates:
                        log.info(f"No available {target_type} instruments to enter")
                    else:
                        # Pick the highest-scored (closest to ATM) candidate
                        best = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)[0]
                        log.info(f"Signal: Nifty {nifty_signal} → entering {best['symbol']}")
                        self._try_enter(best, nifty_signal, nifty_score, nifty_reason)

                # ── Write heartbeat for dashboard ────────────────────────────
                self._write_state()

                # ── Wait before next full cycle ──────────────────────────────
                time.sleep(Config.POLL_SECONDS)

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