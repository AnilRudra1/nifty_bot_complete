from datetime import datetime, time
from config import Config
from utils.logger import get_logger

log = get_logger("risk")

INITIAL_SL_POINTS = 10
BREAKEVEN_GAP     = 5


class RiskManager:
    def __init__(self):
        self.daily_pnl    = 0.0
        self.trades_today = 0
        self.bot_paused   = False
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
        sq_off  = time(Config.SQUARE_OFF_HOUR, Config.SQUARE_OFF_MINUTE)
        close_t = time(15, 30)
        if now < open_t:
            return False, "Market not open yet"
        if now >= close_t:
            return False, "Market closed"
        if now < avoid_t:
            return False, f"Avoiding first {Config.AVOID_OPEN_MINUTES} min"
        if now >= sq_off:
            return False, "Past square-off time"
        return True, "OK"

    def should_square_off(self):
        return datetime.now().time() >= time(
            Config.SQUARE_OFF_HOUR, Config.SQUARE_OFF_MINUTE
        )

    def is_expiry_day(self):
        return datetime.now().weekday() == 1

    def can_trade(self):
        self._check_reset()
        if self.bot_paused:
            return False, "Bot paused"
        allowed, reason = self.is_trading_time()
        if not allowed:
            return False, reason
        return True, "OK"

    def record_trade_open(self):
        self.trades_today += 1

    def record_trade_close(self, pnl):
        self.daily_pnl += pnl
        log.info(f"Trade P&L: Rs.{pnl:,.0f} | Day P&L: Rs.{self.daily_pnl:,.0f}")

    def initial_stop_loss(self, entry: float, direction: str) -> float:
        """Initial SL is always exactly 10 points from entry."""
        if direction == "BUY":
            return round(entry - INITIAL_SL_POINTS, 2)
        return round(entry + INITIAL_SL_POINTS, 2)

    def trail_stop_loss(self, current_sl: float, current_price: float,
                        entry: float, direction: str) -> float:
        """
        Stepped trailing SL.
        Before breakeven: gap = 10 points, trails 1:1
        After breakeven:  gap = 5 points,  trails 1:1
        SL never moves backwards.
        """
        if direction == "BUY":
            if current_sl >= entry:
                # Phase 2 — past breakeven, 5 point gap
                new_sl = round(current_price - BREAKEVEN_GAP, 2)
            else:
                # Phase 1 — before breakeven, 10 point gap
                new_sl = round(current_price - INITIAL_SL_POINTS, 2)
            return max(current_sl, new_sl)
        else:
            if current_sl <= entry:
                # Phase 2 — past breakeven, 5 point gap
                new_sl = round(current_price + BREAKEVEN_GAP, 2)
            else:
                # Phase 1 — before breakeven, 10 point gap
                new_sl = round(current_price + INITIAL_SL_POINTS, 2)
            return min(current_sl, new_sl)

    def get_sl_phase(self, current_sl: float, entry: float, direction: str) -> str:
        if direction == "BUY":
            return "BREAKEVEN" if current_sl >= entry else "TRAILING"
        return "BREAKEVEN" if current_sl <= entry else "TRAILING"
