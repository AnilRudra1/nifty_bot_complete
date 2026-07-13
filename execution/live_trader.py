"""
Live trading engine. Identical logic to paper_trader.py but calls
client.place_order() for real order execution.

DO NOT RUN THIS until you have:
1. Paper traded profitably for at least 2-3 months
2. Verified strategy edge on real historical data backtest
3. Set TRADING_MODE=live in .env
4. Double-checked position sizing and daily limits in .env

Safety guard: will refuse to run if TRADING_MODE != 'live' in .env
"""

import time
import pandas as pd
from datetime import datetime, timedelta
from config import Config
from broker.angelone_client import AngelOneClient
from strategy.signal_engine import generate_signals
from risk.risk_manager import RiskManager
from notifications.telegram_notifier import (
    notify_entry, notify_exit, notify_signal, notify_sl_trail,
    notify_error, notify_bot_started, notify_bot_stopped, notify_daily_limit_hit
)
from utils.logger import get_logger
from utils.heartbeat import write_heartbeat, mark_stopped

log = get_logger("live_trader")

POLL_SECONDS     = 30   # faster than paper since real money involved
LOOKBACK_CANDLES = 150


class LiveTrader:
    def __init__(self, instruments: list):
        if Config.TRADING_MODE != "live":
            raise RuntimeError(
                "TRADING_MODE in .env is not set to 'live'. "
                "Set TRADING_MODE=live only when you are ready for real trading."
            )
        self.instruments = instruments
        self.client      = AngelOneClient()
        self.risk        = RiskManager()
        self.positions   = {}   # symbol -> {direction, entry, sl, qty, order_id, ...}
        self.trades      = []
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

    def _place_order(self, instrument: dict, transaction_type: str, qty: int,
                     order_type: str = "MARKET") -> dict | None:
        return self.client.place_order(
            trading_symbol=instrument["symbol"],
            token=instrument["token"],
            exchange=instrument["exchange"],
            transaction_type=transaction_type,
            quantity=qty,
            order_type=order_type,
        )

    def _check_exits(self, symbol: str, instrument: dict, row: pd.Series):
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

        should_exit, exit_reason = False, ""
        if pos["direction"] == "BUY" and row["low"] <= pos["sl"]:
            should_exit, exit_reason = True, "TRAIL_SL"
        elif pos["direction"] == "SELL" and row["high"] >= pos["sl"]:
            should_exit, exit_reason = True, "TRAIL_SL"
        if self.risk.should_square_off():
            should_exit, exit_reason = True, "SQUARE_OFF"

        if should_exit:
            exit_order_type = "BUY" if pos["direction"] == "SELL" else "SELL"
            resp = self._place_order(instrument, exit_order_type, pos["qty"])
            exit_price = cur_price  # actual fill may differ slightly
            if resp:
                log.info(f"[{symbol}] Exit order placed: {resp}")
            else:
                notify_error(f"Exit order FAILED for {symbol}")
            self._close_position(symbol, exit_price, exit_reason)

    def _close_position(self, symbol: str, exit_price: float, reason: str):
        pos    = self.positions.pop(symbol, None)
        if not pos: return
        pnl_pts = (exit_price - pos["entry"]) if pos["direction"] == "BUY" \
            else (pos["entry"] - exit_price)
        pnl_rs  = round(pnl_pts * pos["qty"] - 40, 2)
        self.trades.append({**pos, "exit": exit_price, "exit_time": datetime.now(),
                            "pnl_points": round(pnl_pts, 2), "pnl_rupees": pnl_rs, "reason": reason})
        self.risk.record_trade_close(pnl_rs)
        notify_exit(symbol, pos["direction"], pos["entry"], exit_price, pnl_rs, reason)

        if self.risk.daily_pnl <= -abs(Config.MAX_LOSS_PER_DAY):
            notify_daily_limit_hit("Daily Loss", self.risk.daily_pnl)

    def _check_entries(self, symbol: str, instrument: dict, row: pd.Series):
        if symbol in self.positions: return
        allowed, reason = self.risk.can_trade()
        if not allowed: return
        if not row.get("signal"): return

        direction = row["signal"]
        score     = row.get("signal_score", 0)
        entry     = row["close"]
        atr       = row.get("atr", 50) or 50
        sl        = self.risk.initial_stop_loss(entry, atr, direction)
        qty       = self.risk.calculate_quantity(entry, sl)

        resp = self._place_order(instrument, direction, qty)
        if not resp:
            notify_error(f"Entry order FAILED for {symbol}")
            return

        self.positions[symbol] = {
            "symbol": symbol, "direction": direction,
            "entry": entry, "sl": sl, "atr": atr,
            "qty": qty, "entry_time": datetime.now(),
            "order_id": resp.get("data", {}).get("orderid", ""),
        }
        self.risk.record_trade_open()
        notify_signal(symbol, direction, score, row.get("signal_reason", ""), entry)
        notify_entry(symbol, direction, entry, sl, entry, qty)

    def save_log(self):
        import os
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        if self.trades:
            pd.DataFrame(self.trades).to_csv(Config.TRADE_LOG_PATH, index=False)

    def run(self):
        self.client.login()
        self.running = True
        notify_bot_started("LIVE")
        log.info("LIVE trading started.")

        try:
            while self.running:
                for inst in self.instruments:
                    symbol = inst["symbol"]
                    try:
                        df  = self._fetch(inst)
                        if df.empty: continue
                        df  = generate_signals(df)
                        row = df.iloc[-1]
                        self._check_exits(symbol, inst, row)
                        self._check_entries(symbol, inst, row)
                    except Exception as e:
                        log.error(f"Error {symbol}: {e}")
                        notify_error(f"{symbol}: {str(e)[:100]}")

                write_heartbeat({
                    "mode": "live", "positions": list(self.positions.keys()),
                    "trades_today": self.risk.trades_today, "daily_pnl": self.risk.daily_pnl,
                })
                time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            self.running = False
            self.save_log()
            mark_stopped()
            notify_bot_stopped("manual stop")
