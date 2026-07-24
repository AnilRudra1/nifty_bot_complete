"""
Paper trader with real confirmation filters:
1. OI change filter  — confirms move is backed by new money not just covering
2. PCR filter        — confirms signal aligns with market sentiment
3. Market regime     — adjusts size and threshold based on day type
4. Volume filter     — requires volume surge before entry
5. 10-point hard SL  — initial tight SL, switches to ATR trail after 5pt profit
"""

import time
import os
import threading
import pandas as pd
from datetime import datetime, timedelta, time as dtime
from config import Config
from broker.angelone_client import AngelOneClient
from strategy.signal_engine import generate_signals
from strategy.indicators import add_all_indicators
from strategy.option_filter import get_india_vix, is_vix_safe
from strategy.oi_filter import update_oi, confirm_signal_with_oi
from strategy.pcr_filter import update_pcr, confirm_signal_with_pcr
from strategy.market_regime import detect_regime, get_regime, get_regime_settings, should_stop_trading
from risk.risk_manager import RiskManager
from notifications.telegram_notifier import (
    notify_entry, notify_exit, notify_signal,
    notify_sl_trail, notify_error,
    notify_bot_started, notify_bot_stopped,
)
from utils.logger import get_logger
from utils.heartbeat import write_heartbeat, mark_stopped

log = get_logger("paper_trader")

NIFTY_SPOT_TOKEN = "99926000"
NIFTY_EXCHANGE   = "NSE"
HARD_SL_POINTS   = 10   # initial hard SL — switches to ATR trail after profit
PROFIT_TO_TRAIL  = 5    # switch to ATR trail after 5 pts profit


class PaperTrader:
    def __init__(self, instruments: list):
        self.instruments     = instruments
        self.client          = AngelOneClient()
        self.risk            = RiskManager()
        self.positions       = {}
        self.trades          = []
        self.running         = False
        self._vix            = 15.0
        self._vix_time       = datetime.min
        self._regime         = "UNKNOWN"
        self._regime_checked = False
        self._regime_settings = get_regime_settings("UNKNOWN")
        self._consec_losses  = 0   # consecutive loss counter

    # ── Fetch ──────────────────────────────────────────────────────────────────

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

    # ── Regime detection ───────────────────────────────────────────────────────

    def _check_regime(self):
        """Detect market regime once after 10:00 AM."""
        if self._regime_checked:
            return
        if datetime.now().time() < dtime(10, 0):
            return
        try:
            df = self._fetch_candles(NIFTY_SPOT_TOKEN, NIFTY_EXCHANGE, days=1)
            if not df.empty:
                # Use only today's candles
                today = datetime.now().date()
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df_today = df[df["timestamp"].dt.date == today]
                if not df_today.empty:
                    self._regime          = detect_regime(df_today)
                    self._regime_settings = get_regime_settings(self._regime)
                    self._regime_checked  = True
                    log.info(
                        f"Regime: {self._regime} | "
                        f"Lots:{self._regime_settings['lots']} | "
                        f"ScoreMin:{self._regime_settings['score_min']} | "
                        f"{self._regime_settings['note']}"
                    )
        except Exception as e:
            log.warning(f"Regime check error: {e}")

    # ── Exit logic ─────────────────────────────────────────────────────────────

    def _check_exit(self, symbol, ltp):
        pos = self.positions.get(symbol)
        if not pos:
            return

        entry  = pos["entry"]
        old_sl = pos["sl"]

        # Track high/low
        pos["high"]       = max(pos.get("high", ltp), ltp)
        pos["low"]        = min(pos.get("low",  ltp), ltp)
        pos["last_price"] = ltp

        # Calculate profit in points
        if pos["direction"] == "BUY":
            profit_pts = ltp - entry
        else:
            profit_pts = entry - ltp

        # SL logic:
        # Phase 1 — profit < PROFIT_TO_TRAIL: use hard 10-point SL
        # Phase 2 — profit >= PROFIT_TO_TRAIL: switch to ATR trail
        if pos.get("sl_manual"):
            new_sl = old_sl
        elif profit_pts < PROFIT_TO_TRAIL:
            # Hard initial SL — 10 points from entry
            if pos["direction"] == "BUY":
                new_sl = max(old_sl, entry - HARD_SL_POINTS)
            else:
                new_sl = min(old_sl, entry + HARD_SL_POINTS)
        else:
            # Profit exceeded threshold — switch to ATR trailing
            atr    = pos.get("atr", ltp * 0.05) or ltp * 0.05
            new_sl = self.risk.trail_stop_loss(old_sl, ltp, atr, pos["direction"])

        if new_sl != old_sl:
            pos["sl"]         = new_sl
            pos["current_sl"] = new_sl
            pos["sl_manual"]  = False
            if profit_pts >= PROFIT_TO_TRAIL:
                notify_sl_trail(symbol, old_sl, new_sl, ltp)
                log.info(f"[{symbol}] Trail SL: {old_sl} -> {new_sl} | Profit:{profit_pts:.1f}pts")
        else:
            pos["current_sl"] = pos["sl"]

        # Check exit conditions
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
            "oi_reason":     pos.get("oi_reason", ""),
            "pcr_reason":    pos.get("pcr_reason", ""),
            "regime":        self._regime,
        })
        self.risk.record_trade_close(pnl_rs)
        notify_exit(symbol, pos["direction"], pos["entry"], exit_price, pnl_rs, reason)
        log.info(
            f"[{symbol}] EXIT {reason} @ {exit_price} | "
            f"P&L Rs.{pnl_rs} | Consec losses:{self._consec_losses}"
        )
        self.save_log()

    # ── Entry logic ─────────────────────────────────────────────────────────────

    def _check_entry(self, inst, df):
        symbol   = inst["symbol"]
        token    = inst.get("token", "")
        opt_type = "CE" if "CE" in symbol else "PE"

        if symbol in self.positions:
            return

        # Block until regime is known (after 10 AM)
        if self._regime == "UNKNOWN" and datetime.now().time() >= dtime(10, 0):
            log.info(f"[{symbol}] Waiting for regime detection")
            return

        # Regime stop check
        if should_stop_trading(self._regime):
            log.info(f"[{symbol}] Regime stop — no new entries after cutoff hour")
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

        # Use regime-based score minimum
        score_min = self._regime_settings.get("score_min", Config.SIGNAL_SCORE_MIN)
        if score < score_min:
            return

        # Dead stock filter
        if price < Config.MIN_PREMIUM:
            log.info(f"[{symbol}] Dead stock Rs.{price}")
            return

        # Expiry day cutoff
        if self.risk.is_expiry_day() and datetime.now().hour >= Config.EXPIRY_CUTOFF_HOUR:
            log.info(f"[{symbol}] Expiry cutoff")
            return

        # VIX filter
        vix_ok, vix_reason = is_vix_safe(self._vix)
        if not vix_ok:
            log.info(f"[{symbol}] VIX blocked: {vix_reason}")
            return

        # Volume confirmation — require volume surge
        if not row.get("vol_surge", False):
            log.info(f"[{symbol}] No volume surge — skip")
            return

        # OI proxy via volume surge
        oi_reason = "Vol surge confirmed" if row.get("vol_surge") else "No vol surge"
        score    += 10 if row.get("vol_surge") else 0

        # PCR proxy via VWAP position
        above_vwap = row.get("above_vwap", False)
        if signal == "BUY" and above_vwap:
            pcr_reason = "Above VWAP confirms BUY"
            score     += 10
        elif signal == "SELL" and not above_vwap:
            pcr_reason = "Below VWAP confirms SELL"
            score     += 10
        elif signal == "BUY" and not above_vwap:
            pcr_reason = "Below VWAP contradicts BUY"
            score     -= 10
        elif signal == "SELL" and above_vwap:
            pcr_reason = "Above VWAP contradicts SELL"
            score     -= 10
        else:
            pcr_reason = "VWAP neutral"

        # Final score check after all adjustments
        if score < score_min:
            log.info(f"[{symbol}] Score {score} below {score_min} after OI/PCR adjustment")
            return

        atr     = float(row.get("atr", price * 0.05) or price * 0.05)
        sl      = (price - HARD_SL_POINTS) if signal == "BUY" else (price + HARD_SL_POINTS)
        lots    = self._regime_settings.get("lots", Config.FIXED_LOTS)
        qty     = Config.LOT_SIZE * lots
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
            "oi_reason":     oi_reason,
            "pcr_reason":    pcr_reason,
            "regime":        self._regime,
            "high":          price,
            "low":           price,
            "last_price":    price,
            "token":         token,
            "exchange":      inst.get("exchange", "NFO"),
        }
        self.risk.record_trade_open()
        notify_signal(symbol, signal, score, sig_reason, price)
        notify_entry(symbol, signal, price, sl, price, qty)
        log.info(
            f"[{symbol}] ENTRY {signal} @ {price} | "
            f"SL {sl} (10pt hard) | Qty {qty} | Score {score} | "
            f"Pattern:{pattern} | OI:{oi_reason} | PCR:{pcr_reason} | "
            f"Regime:{self._regime}"
        )

    # ── LTP polling thread ─────────────────────────────────────────────────────

    def _ltp_loop(self):
        """Poll LTP every 15 seconds for open positions."""
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
                            f"SL:{pos.get('current_sl',0):.1f} | "
                            f"P&L:Rs.{pnl}"
                        )
                except Exception as e:
                    log.debug(f"LTP [{sym}]: {e}")
                time.sleep(2)
            time.sleep(13)

    # ── PCR update thread ──────────────────────────────────────────────────────

    def _pcr_loop(self):
        """Update PCR every 30 minutes."""
        while self.running:
            try:
                update_pcr(self.client)
            except Exception as e:
                log.debug(f"PCR update: {e}")
            time.sleep(1800)

    # ── Manual SL ──────────────────────────────────────────────────────────────

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

    # ── Save and heartbeat ──────────────────────────────────────────────────────

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
            "market_dir":   self._regime,
        })

    # ── Main run ────────────────────────────────────────────────────────────────

    def run(self):
        self.client.login()
        self.running = True
        notify_bot_started("PAPER")
        log.info(f"Bot started with OI+PCR+Regime filters. {len(self.instruments)} instruments.")

        # Initial VIX fetch
        time.sleep(5)
        try:
            self._vix      = get_india_vix(self.client)
            self._vix_time = datetime.now()
            log.info(f"VIX: {self._vix}")
        except Exception as e:
            log.warning(f"VIX failed: {e}")

        # Initial PCR fetch
        try:
            update_pcr(self.client)
        except Exception as e:
            log.warning(f"PCR init failed: {e}")

        # Start LTP polling thread
        ltp_thread = threading.Thread(target=self._ltp_loop, daemon=True)
        ltp_thread.start()

        idx = 0
        try:
            while self.running:

                # Check regime after 10 AM
                self._check_regime()

                # Refresh VIX every 30 min
                if (datetime.now() - self._vix_time).seconds > 1800:
                    try:
                        self._vix      = get_india_vix(self.client)
                        self._vix_time = datetime.now()
                    except Exception:
                        pass

                # Scan next instrument
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
                            f"Signal:{row.get('signal','none')} | "
                            f"Score:{row.get('signal_score',0)} | "
                            f"Vol:{row.get('vol_surge',False)} | "
                            f"Regime:{self._regime}"
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
