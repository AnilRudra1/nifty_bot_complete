"""
Real-time Nifty price feed from NSE India website.
No API key needed. No rate limits. Updates every few seconds.
We build our own candles from these live prices.
"""

import requests
import time
import threading
from datetime import datetime
from utils.logger import get_logger

log = get_logger("nse_feed")

NSE_URL     = "https://www.nseindia.com/api/quote-equity?symbol=NIFTY%2050&series=EQ"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Referer":    "https://www.nseindia.com",
}

# Simpler endpoint — NSE option chain has Nifty spot price
NSE_OC_URL  = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"


class NSEFeed:
    """
    Polls NSE website every few seconds for live Nifty spot price.
    Builds 1-minute and 5-minute candles from those ticks.
    Calls on_candle_complete(candle, timeframe) when a candle closes.
    """
    def __init__(self, on_tick=None, on_candle=None, interval_sec=5, angel_client=None):
        self._angel_client = angel_client
        self.on_tick          = on_tick    # called on every price update
        self.on_candle        = on_candle  # called when 5-min candle completes
        self.interval_sec     = interval_sec
        self.running          = False
        self._session         = requests.Session()
        self._session.headers.update(NSE_HEADERS)
        self._candle_1m       = None
        self._candle_5m       = None
        self._candle_1m_start = None
        self._candle_5m_start = None
        self._last_price      = 0
        self.candles_5m       = []  # completed 5-min candles
        self.candles_1m       = []  # completed 1-min candles

        # Warm up session with homepage first
        try:
            self._session.get("https://www.nseindia.com", timeout=5)
        except:
            pass

    def _fetch_nifty_price(self) -> float:
        """
        Fetch Nifty spot price via Angel One LTP.
        ltpData API is NOT rate limited like getCandleData.
        Completely separate endpoint, can call every 5 seconds safely.
        """
        try:
            if not hasattr(self, '_angel_client') or not self._angel_client:
                return 0.0
            ltp = self._angel_client.get_ltp("NSE", "Nifty 50", "99926000")
            if ltp and ltp > 0:
                log.info(f"Nifty LTP: {ltp}")
                return float(ltp)
            return 0.0
        except Exception as e:
            log.error(f"LTP fetch error: {e}")
            return 0.0

    def _snap(self, dt, minutes):
        """Snap datetime to candle boundary."""
        m = (dt.minute // minutes) * minutes
        return dt.replace(minute=m, second=0, microsecond=0)

    def _add_to_candle(self, candle, price):
        """Update an existing candle with new price."""
        candle["high"]  = max(candle["high"], price)
        candle["low"]   = min(candle["low"], price)
        candle["close"] = price
        candle["ticks"] = candle.get("ticks", 0) + 1
        return candle

    def _process_tick(self, price: float):
        now      = datetime.now()
        snap_1m  = self._snap(now, 1)
        snap_5m  = self._snap(now, 5)

        # ── 1-minute candle ──────────────────────────────────────────────────
        if self._candle_1m_start != snap_1m:
            # Close previous candle
            if self._candle_1m:
                self.candles_1m.append(self._candle_1m.copy())
                if len(self.candles_1m) > 500:
                    self.candles_1m = self.candles_1m[-500:]
                if self.on_candle:
                    self.on_candle(self._candle_1m.copy(), "1m")
            # Start new candle
            self._candle_1m_start = snap_1m
            self._candle_1m = {
                "timestamp": snap_1m,
                "open":      price,
                "high":      price,
                "low":       price,
                "close":     price,
                "volume":    0,
                "ticks":     1,
            }
        else:
            if self._candle_1m:
                self._candle_1m = self._add_to_candle(self._candle_1m, price)

        # ── 5-minute candle ──────────────────────────────────────────────────
        if self._candle_5m_start != snap_5m:
            if self._candle_5m:
                self.candles_5m.append(self._candle_5m.copy())
                if len(self.candles_5m) > 300:
                    self.candles_5m = self.candles_5m[-300:]
                log.info(f"5m candle closed: O:{self._candle_5m['open']} H:{self._candle_5m['high']} L:{self._candle_5m['low']} C:{self._candle_5m['close']}")
                if self.on_candle:
                    self.on_candle(self._candle_5m.copy(), "5m")
            self._candle_5m_start = snap_5m
            self._candle_5m = {
                "timestamp": snap_5m,
                "open":      price,
                "high":      price,
                "low":       price,
                "close":     price,
                "volume":    0,
                "ticks":     1,
            }
        else:
            if self._candle_5m:
                self._candle_5m = self._add_to_candle(self._candle_5m, price)

    def _poll_loop(self):
        log.info(f"NSE feed started — polling every {self.interval_sec}s")
        while self.running:
            try:
                price = self._fetch_nifty_price()
                if price > 0:
                    self._last_price = price
                    self._process_tick(price)
                    if self.on_tick:
                        self.on_tick(price, datetime.now())
                else:
                    log.debug("NSE returned 0 price, skipping tick")
            except Exception as e:
                log.error(f"NSE poll error: {e}")
            time.sleep(self.interval_sec)

    def start(self):
        self.running = True
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        log.info("NSE feed thread started")
        return t

    def stop(self):
        self.running = False

    @property
    def last_price(self):
        return self._last_price

    def get_current_candle(self):
        return self._candle_5m
