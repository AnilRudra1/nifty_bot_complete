"""
Risk manager. Handles everything related to protecting capital:

- Position sizing (risk fixed % of capital per trade)
- ATR-based trailing stop loss (moves in your favour, never backwards)
- Daily loss limit (stops bot for the day if breached)
- Max trades per day limit
- Time filters (no trades in first/last 15 min, auto square off at 3:15 PM)
- Gap detection (skip or reduce size on gap open days)
- Expiry day flag
"""

from datetime import datetime, time
from config import Config
from utils.logger import get_logger

log = get_logger("risk")


class RiskManager:
    def __init__(self):
        self.daily_pnl      = 0.0
        self.trades_today   = 0
        self.bot_paused     = False   # manually paused from dashboard
        self._reset_day()

    def _reset_day(self):
        self.daily_pnl    = 0.0
        self.trades_today = 0
        self._today       = datetime.now().date()

    def _check_day_reset(self):
        if datetime.now().date() != self._today:
            log.info("New trading day — resetting daily counters")
            self._reset_day()

    # ── Time filters ──────────────────────────────────────────────────────────

    def is_trading_time(self) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        False if outside market hours, in no-entry window, or past square-off time.
        """
        self._check_day_reset()
        now = datetime.now().time()
        open_t  = time(9, 15)
        avoid_t = time(9, 15 + Config.AVOID_OPEN_MINUTES)  # 9:30
        close_t = time(15, 30)
        sq_off  = time(15, 15)

        if now < open_t:
            return False, "Market not open yet"
        if now >= close_t:
            return False, "Market closed"
        if now < avoid_t:
            return False, f"Avoiding first {Config.AVOID_OPEN_MINUTES} min (9:15–9:30)"
        if now >= sq_off:
            return False, "Past square-off time (15:15) — no new entries"
        return True, "OK"

    def should_square_off(self) -> bool:
        """Returns True if all open positions must be closed immediately."""
        return datetime.now().time() >= time(15, 15)

    def is_expiry_day(self) -> bool:
        """Thursday = weekly expiry day. Extra caution warranted."""
        return datetime.now().weekday() == 3  # Thursday

    # ── Daily limits ──────────────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        """Master check before any new entry."""
        self._check_day_reset()

        # Skip trading on expiry day after 2 PM
        if self.risk.is_expiry_day() and datetime.now().time() >= time(14, 0):
            return

        # Don't trade options with premium below ₹5
        if row["close"] < 5:
            return

        if self.bot_paused:
            return False, "Bot paused from dashboard"

        allowed, reason = self.is_trading_time()
        if not allowed:
            return False, reason

        if self.daily_pnl <= -abs(Config.MAX_LOSS_PER_DAY):
            return False, f"Daily loss limit hit (₹{Config.MAX_LOSS_PER_DAY:,.0f})"

        if self.trades_today >= Config.MAX_TRADES_PER_DAY:
            return False, f"Max {Config.MAX_TRADES_PER_DAY} trades/day reached"

        if self.is_expiry_day():
            log.warning("Expiry day — signals taken with lower confidence only")

        return True, "OK"

    def record_trade_open(self):
        self.trades_today += 1

    def record_trade_close(self, pnl: float):
        self.daily_pnl += pnl
        log.info(f"Trade closed P&L: ₹{pnl:,.0f} | Day P&L: ₹{self.daily_pnl:,.0f}")

    # ── Position sizing ───────────────────────────────────────────────────────

    def calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
        """
        Risk a fixed % of capital per trade. Quantity = max lots such that
        (entry - SL) * qty * lot_size <= risk_amount.
        Always returns at least 1 lot.
        """
        risk_amount   = Config.CAPITAL * Config.RISK_PER_TRADE_PCT / 100
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return Config.LOT_SIZE
        qty = int(risk_amount / risk_per_unit)
        qty = max(qty, Config.LOT_SIZE)  # minimum 1 lot
        return qty

    # ── ATR-based trailing stop loss ──────────────────────────────────────────

    def initial_stop_loss(self, entry: float, atr: float, direction: str) -> float:
        """Set initial stop loss at entry ± ATR * multiplier."""
        offset = atr * Config.ATR_TRAIL_MULTIPLIER
        if direction == "BUY":
            return round(entry - offset, 2)
        return round(entry + offset, 2)

    def trail_stop_loss(self, current_sl: float, current_price: float,
                        atr: float, direction: str) -> float:
        """
        Trail the stop loss as price moves in our favour.
        For BUY: new SL = max(current_sl, price - ATR*mult) — only moves up
        For SELL: new SL = min(current_sl, price + ATR*mult) — only moves down
        """
        offset = atr * Config.ATR_TRAIL_MULTIPLIER
        if direction == "BUY":
            new_sl = round(current_price - offset, 2)
            return max(current_sl, new_sl)   # never move SL down
        else:
            new_sl = round(current_price + offset, 2)
            return min(current_sl, new_sl)   # never move SL up

    # ── Gap detection ─────────────────────────────────────────────────────────

    def is_gap_open(self, prev_close: float, today_open: float,
                    gap_pct: float = 0.5) -> tuple[bool, str]:
        """
        Returns (True, 'gap_up'|'gap_down') if today opened more than
        gap_pct% away from yesterday's close. False otherwise.
        """
        change_pct = (today_open - prev_close) / prev_close * 100
        if change_pct > gap_pct:
            return True, "gap_up"
        if change_pct < -gap_pct:
            return True, "gap_down"
        return False, ""
