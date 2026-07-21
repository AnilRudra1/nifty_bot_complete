from datetime import datetime, time
from config import Config
from utils.logger import get_logger

log = get_logger("risk")

class RiskManager:
    def __init__(self):
        self.daily_pnl    = 0.0
        self.trades_today = 0
        self._today       = datetime.now().date()

    def _check_reset(self):
        if datetime.now().date() != self._today:
            log.info("New day — resetting counters")
            self.daily_pnl    = 0.0
            self.trades_today = 0
            self._today       = datetime.now().date()

    def is_trading_time(self):
        self._check_reset()
        now     = datetime.now().time()
        open_t  = time(9, 15)
        avoid_t = time(9, 15 + Config.AVOID_OPEN_MINUTES)
        close_t = time(15, 30)
        sq_off  = time(Config.SQUARE_OFF_HOUR, Config.SQUARE_OFF_MINUTE)
        if now < open_t:
            return False, "Market not open yet"
        if now >= close_t:
            return False, "Market closed"
        if now < avoid_t:
            return False, f"Avoiding first {Config.AVOID_OPEN_MINUTES} min"
        if now >= sq_off:
            return False, "Past square-off time — no new entries"
        return True, "OK"

    def should_square_off(self):
        return datetime.now().time() >= time(Config.SQUARE_OFF_HOUR, Config.SQUARE_OFF_MINUTE)

    def is_expiry_day(self):
        return datetime.now().weekday() == 1  # Tuesday weekly expiry

    def can_trade(self):
        self._check_reset()
        allowed, reason = self.is_trading_time()
        if not allowed:
            return False, reason
        return True, "OK"

    def record_trade_open(self):
        self.trades_today += 1

    def record_trade_close(self, pnl):
        self.daily_pnl += pnl
        log.info(f"Trade P&L: ₹{pnl:,.0f} | Day P&L: ₹{self.daily_pnl:,.0f}")

    def initial_stop_loss(self, entry, atr, direction):
        offset = max(atr * Config.ATR_TRAIL_MULTIPLIER, entry * 0.03)
        if direction == "BUY":
            return round(entry - offset, 2)
        return round(entry + offset, 2)

    def trail_stop_loss(self, current_sl, current_price, atr, direction):
        offset = max(atr * Config.ATR_TRAIL_MULTIPLIER, current_price * 0.03)
        if direction == "BUY":
            new_sl = round(current_price - offset, 2)
            return max(current_sl, new_sl)
        else:
            new_sl = round(current_price + offset, 2)
            return min(current_sl, new_sl)
