"""
Data Collector — Tick Recorder for Pattern Discovery

Runs silently alongside the trading bot.
Records every price tick for all 10 option instruments + Nifty spot.
After market close, automatically tags every tick with:
  - Did price move 20+ points in next 5 minutes? (big_move_up / big_move_down)
  - Did price move 10+ points? (medium_move)
  - What was the candle pattern context at that moment?
  - What were all indicator values?

After one month of data, run pattern_discovery.py to find
what conditions consistently preceded the big moves.

Usage:
    python3 data_collector.py

Runs independently from main.py — no interference.
"""

import os
import time
import json
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dtime
from collections import defaultdict

# ── Import from main bot ───────────────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker.angelone_client import AngelOneClient
from data.instrument_selector import select_instruments
from strategy.candlestick_patterns import apply_all_patterns
from strategy.indicators import add_all_indicators
from config import Config
from utils.logger import get_logger

log = get_logger("data_collector")

# ── Settings ───────────────────────────────────────────────────────────────────
TICK_INTERVAL_SEC  = 15      # record price every 5 seconds
BIG_MOVE_POINTS    = 20     # tag as big move if price moves 20+ points
MEDIUM_MOVE_POINTS = 10     # tag as medium move if 10+ points
LOOKBACK_WINDOW    = 60     # seconds to look forward for move detection (1 min)
CANDLE_MINUTES     = 5      # 5-minute candles for pattern context
DATA_DIR           = "data/tick_data"
NIFTY_SPOT_TOKEN   = "99926000"
NIFTY_EXCHANGE     = "NSE"


# ── Candle builder ─────────────────────────────────────────────────────────────

class CandleBuilder:
    """Builds 5-min candles from live ticks."""
    def __init__(self):
        self.candles  = []
        self.current  = None
        self._c_start = None

    def add_tick(self, price: float, volume: float = 0) -> bool:
        now    = datetime.now()
        minute = (now.minute // CANDLE_MINUTES) * CANDLE_MINUTES
        snap   = now.replace(minute=minute, second=0, microsecond=0)
        completed = False

        if self._c_start and snap > self._c_start:
            if self.current:
                self.candles.append(self.current.copy())
                if len(self.candles) > 500:
                    self.candles = self.candles[-500:]
                completed = True
            self.current  = None
            self._c_start = None

        if self.current is None:
            self._c_start = snap
            self.current  = {
                "timestamp": snap,
                "open":      price,
                "high":      price,
                "low":       price,
                "close":     price,
                "volume":    volume,
            }
        else:
            self.current["high"]   = max(self.current["high"], price)
            self.current["low"]    = min(self.current["low"],  price)
            self.current["close"]  = price
            self.current["volume"] += volume

        return completed

    def get_df(self) -> pd.DataFrame:
        candles = self.candles.copy()
        if self.current:
            candles.append(self.current.copy())
        return pd.DataFrame(candles) if candles else pd.DataFrame()

    def get_indicators(self) -> dict:
        """Get current indicator values from candle history."""
        df = self.get_df()
        if len(df) < 10:
            return {}
        try:
            df = add_all_indicators(df)
            df = apply_all_patterns(df)
            row = df.iloc[-1]

            # Find active pattern
            pattern = ""
            for col in df.columns:
                if col.startswith("pat_") and row.get(col):
                    pattern = col.replace("pat_", "").replace("_", " ").title()
                    break

            return {
                "rsi":          round(float(row.get("rsi", 50) or 50), 2),
                "vwap":         round(float(row.get("vwap", 0) or 0), 2),
                "above_vwap":   bool(row.get("above_vwap", False)),
                "ema_bull":     bool(row.get("ema_bull", False)),
                "ema_bear":     bool(row.get("ema_bear", False)),
                "atr":          round(float(row.get("atr", 0) or 0), 2),
                "adx":          round(float(row.get("adx", 0) or 0), 2),
                "is_trending":  bool(row.get("is_trending", False)),
                "vol_surge":    bool(row.get("vol_surge", False)),
                "pattern":      pattern,
                "candle_range": round(float(row.get("range", 0) or 0), 2),
                "body_pct":     round(float(row.get("body_pct", 0) or 0), 2),
                "is_bull_candle": bool(row.get("is_bull", False)),
                "is_bear_candle": bool(row.get("is_bear", False)),
            }
        except Exception as e:
            log.debug(f"Indicator error: {e}")
            return {}


# ── Tick store ─────────────────────────────────────────────────────────────────

class TickStore:
    """Stores all ticks for one instrument during the trading day."""
    def __init__(self, symbol: str, option_type: str, strike: float):
        self.symbol      = symbol
        self.option_type = option_type
        self.strike      = strike
        self.ticks       = []       # raw tick records
        self.day_open    = None
        self.day_high    = 0.0
        self.day_low     = float("inf")
        self.prev_price  = None
        self.builder     = CandleBuilder()

    def add_tick(self, price: float, nifty_spot: float, volume: float = 0):
        now = datetime.now()

        if self.day_open is None:
            self.day_open = price

        self.day_high = max(self.day_high, price)
        self.day_low  = min(self.day_low,  price)

        price_change       = round(price - self.prev_price, 2) if self.prev_price else 0.0
        price_change_pct   = round(price_change / self.prev_price * 100, 4) if self.prev_price else 0.0
        change_from_open   = round(price - self.day_open, 2)
        change_from_open_pct = round(change_from_open / self.day_open * 100, 4) if self.day_open else 0.0

        minutes_since_open = (now.hour * 60 + now.minute) - (9 * 60 + 15)
        minutes_to_close   = (15 * 60 + 30) - (now.hour * 60 + now.minute)

        # Update candle builder
        self.builder.add_tick(price, volume)

        # Get current indicators
        indicators = self.builder.get_indicators()

        # Get rolling moves
        rolling_1m  = self._rolling_move(60)
        rolling_5m  = self._rolling_move(300)
        rolling_15m = self._rolling_move(900)

        tick = {
            # Identification
            "timestamp":           now.isoformat(),
            "date":                now.strftime("%Y-%m-%d"),
            "time":                now.strftime("%H:%M:%S"),
            "symbol":              self.symbol,
            "option_type":         self.option_type,
            "strike":              self.strike,

            # Price data
            "price":               price,
            "prev_price":          self.prev_price or price,
            "price_change":        price_change,
            "price_change_pct":    price_change_pct,
            "day_open":            self.day_open,
            "day_high":            self.day_high,
            "day_low":             self.day_low,
            "change_from_open":    change_from_open,
            "change_from_open_pct": change_from_open_pct,
            "dist_from_day_high":  round(self.day_high - price, 2),
            "dist_from_day_low":   round(price - self.day_low, 2),

            # Nifty context
            "nifty_spot":          nifty_spot,

            # Time context
            "minutes_since_open":  minutes_since_open,
            "minutes_to_close":    minutes_to_close,
            "hour":                now.hour,
            "minute":              now.minute,
            "is_morning":          9 <= now.hour < 11,
            "is_midday":           11 <= now.hour < 13,
            "is_afternoon":        13 <= now.hour < 15,

            # Rolling moves
            "move_1min":           rolling_1m,
            "move_5min":           rolling_5m,
            "move_15min":          rolling_15m,

            # Indicators (from 5-min candles)
            "rsi":                 indicators.get("rsi", 50),
            "vwap":                indicators.get("vwap", 0),
            "above_vwap":          indicators.get("above_vwap", False),
            "ema_bull":            indicators.get("ema_bull", False),
            "ema_bear":            indicators.get("ema_bear", False),
            "atr":                 indicators.get("atr", 0),
            "adx":                 indicators.get("adx", 0),
            "is_trending":         indicators.get("is_trending", False),
            "vol_surge":           indicators.get("vol_surge", False),
            "pattern":             indicators.get("pattern", ""),
            "candle_range":        indicators.get("candle_range", 0),
            "body_pct":            indicators.get("body_pct", 0),
            "is_bull_candle":      indicators.get("is_bull_candle", False),
            "is_bear_candle":      indicators.get("is_bear_candle", False),

            # Labels — filled in after market close
            "big_move_up":         False,
            "big_move_down":       False,
            "medium_move_up":      False,
            "medium_move_down":    False,
            "move_in_next_1min":   0.0,
            "move_in_next_5min":   0.0,
        }

        self.ticks.append(tick)
        self.prev_price = price

    def _rolling_move(self, seconds_back: int) -> float:
        """Price move over last N seconds."""
        if len(self.ticks) < 2:
            return 0.0
        cutoff = datetime.now() - timedelta(seconds=seconds_back)
        old_ticks = [
            t for t in self.ticks
            if datetime.fromisoformat(t["timestamp"]) >= cutoff
        ]
        if not old_ticks:
            return 0.0
        oldest_price = old_ticks[0]["price"]
        current_price = self.ticks[-1]["price"]
        return round(current_price - oldest_price, 2)

    def tag_moves(self):
        """
        After market close — tag every tick with what happened next.
        For each tick, look forward 1 min and 5 min and record price move.
        Tag big_move_up/down if move >= threshold.
        """
        log.info(f"Tagging {len(self.ticks)} ticks for {self.symbol}")
        ticks_by_time = self.ticks.copy()

        for i, tick in enumerate(ticks_by_time):
            tick_time = datetime.fromisoformat(tick["timestamp"])

            # Find ticks 1 minute ahead
            future_1min = [
                t for t in ticks_by_time[i:]
                if datetime.fromisoformat(t["timestamp"]) <= tick_time + timedelta(minutes=1)
            ]
            # Find ticks 5 minutes ahead
            future_5min = [
                t for t in ticks_by_time[i:]
                if datetime.fromisoformat(t["timestamp"]) <= tick_time + timedelta(minutes=5)
            ]

            if future_1min:
                future_prices_1m   = [t["price"] for t in future_1min]
                max_up_1m          = max(future_prices_1m) - tick["price"]
                max_down_1m        = tick["price"] - min(future_prices_1m)
                tick["move_in_next_1min"] = round(max(max_up_1m, -max_down_1m), 2)

            if future_5min:
                future_prices_5m   = [t["price"] for t in future_5min]
                max_up_5m          = max(future_prices_5m) - tick["price"]
                max_down_5m        = tick["price"] - min(future_prices_5m)

                tick["move_in_next_5min"]  = round(max_up_5m if max_up_5m > max_down_5m else -max_down_5m, 2)
                tick["big_move_up"]        = max_up_5m   >= BIG_MOVE_POINTS
                tick["big_move_down"]      = max_down_5m >= BIG_MOVE_POINTS
                tick["medium_move_up"]     = max_up_5m   >= MEDIUM_MOVE_POINTS
                tick["medium_move_down"]   = max_down_5m >= MEDIUM_MOVE_POINTS

        self.ticks = ticks_by_time

    def save(self, date_str: str):
        """Save ticks to CSV file."""
        if not self.ticks:
            return
        os.makedirs(DATA_DIR, exist_ok=True)
        safe_sym = self.symbol.replace("/", "_")
        path     = f"{DATA_DIR}/{date_str}_{safe_sym}.csv"
        pd.DataFrame(self.ticks).to_csv(path, index=False)
        log.info(f"Saved {len(self.ticks)} ticks -> {path}")


# ── Main collector ─────────────────────────────────────────────────────────────

class DataCollector:
    def __init__(self):
        self.client      = AngelOneClient()
        self.instruments = []
        self.stores      = {}   # symbol -> TickStore
        self.nifty_price = 0.0
        self.running     = False

    def setup(self):
        """Login and select instruments."""
        self.client.login()
        log.info("Selecting instruments...")
        selection = select_instruments(self.client, top_n=5)
        if not selection:
            log.error("Instrument selection failed")
            return False

        self.instruments = (
            selection.get("ce_strikes", []) +
            selection.get("pe_strikes", [])
        )
        log.info(f"Monitoring {len(self.instruments)} instruments")

        # Create tick stores
        for inst in self.instruments:
            sym = inst["symbol"]
            self.stores[sym] = TickStore(
                symbol      = sym,
                option_type = inst.get("option_type", "CE"),
                strike      = inst.get("strike", 0),
            )
        return True

    def _collect_loop(self):
        """Main collection loop — runs every TICK_INTERVAL_SEC seconds."""
        log.info(f"Collection started — recording every {TICK_INTERVAL_SEC}s")

        while self.running:
            market_open  = dtime(9, 15)
            market_close = dtime(15, 30)
            now_time     = datetime.now().time()

            if not (market_open <= now_time <= market_close):
                if now_time > market_close:
                    log.info("Market closed — stopping collection")
                    self.running = False
                    break
                time.sleep(30)
                continue

            # Fetch Nifty spot
            try:
                nifty_ltp = self.client.get_ltp(
                    NIFTY_EXCHANGE, "Nifty 50", NIFTY_SPOT_TOKEN
                )
                if nifty_ltp and nifty_ltp > 0:
                    self.nifty_price = nifty_ltp
            except Exception as e:
                log.debug(f"Nifty LTP error: {e}")

            # Fetch LTP for each instrument with delay between calls
            for inst in self.instruments:
                sym      = inst["symbol"]
                token    = inst.get("token", "")
                exchange = inst.get("exchange", "NFO")

                if not token:
                    continue

                try:
                    ltp = self.client.get_ltp(exchange, sym, token)
                    if ltp and ltp > 0:
                        self.stores[sym].add_tick(
                            price      = ltp,
                            nifty_spot = self.nifty_price,
                            volume     = 0,
                        )
                except Exception as e:
                    log.debug(f"LTP [{sym}]: {e}")

                time.sleep(1)  # 1 second between each instrument LTP call

            time.sleep(TICK_INTERVAL_SEC)

    def _eod_processing(self):
        """End of day — tag moves and save all data."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log.info(f"Running end-of-day processing for {date_str}")

        total_ticks     = 0
        total_big_moves = 0

        for sym, store in self.stores.items():
            # Tag moves
            store.tag_moves()

            # Count big moves
            big_moves = sum(
                1 for t in store.ticks
                if t.get("big_move_up") or t.get("big_move_down")
            )
            total_big_moves += big_moves
            total_ticks     += len(store.ticks)

            log.info(
                f"{sym}: {len(store.ticks)} ticks | "
                f"{big_moves} big move setups found"
            )

            # Save to CSV
            store.save(date_str)

        # Save daily summary
        self._save_daily_summary(date_str, total_ticks, total_big_moves)
        log.info(
            f"EOD complete | Total ticks: {total_ticks:,} | "
            f"Big move setups: {total_big_moves}"
        )

    def _save_daily_summary(self, date_str, total_ticks, total_big_moves):
        """Save a summary of the day's collection."""
        summary = {
            "date":              date_str,
            "instruments":       len(self.instruments),
            "total_ticks":       total_ticks,
            "big_move_setups":   total_big_moves,
            "nifty_final":       self.nifty_price,
            "collection_time":   datetime.now().isoformat(),
        }
        path = f"{DATA_DIR}/summary_{date_str}.json"
        with open(path, "w") as f:
            json.dump(summary, f, indent=2)
        log.info(f"Summary saved -> {path}")

    def run(self):
        if not self.setup():
            return
        self.running = True
        log.info("Data collector running alongside trading bot")
        log.info(f"Saving tick data to: {DATA_DIR}/")

        try:
            self._collect_loop()
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            self._eod_processing()
            log.info("Data collector finished")


if __name__ == "__main__":
    collector = DataCollector()
    collector.run()

