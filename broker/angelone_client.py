"""
Angel One SmartAPI wrapper.
Handles: login (TOTP), candle data, option chain, LTP, and order placement.

Setup:
1. Get API key from https://smartapi.angelbroking.com/
2. Enable TOTP on your Angel One account — the base32 secret shown
   when you scan the QR code goes into ANGEL_TOTP_SECRET in .env
3. pip install -r requirements.txt
"""

import time
import pyotp
import pandas as pd
from datetime import datetime
from config import Config
from utils.logger import get_logger

log = get_logger("broker")

try:
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None
    log.warning("smartapi-python not installed. Run: pip install -r requirements.txt")


class AngelOneClient:
    def __init__(self):
        self.smart_api = None
        self._logged_in = False

    def login(self) -> bool:
        if SmartConnect is None:
            raise RuntimeError("smartapi-python not installed.")
        if not all([Config.ANGEL_API_KEY, Config.ANGEL_CLIENT_ID,
                    Config.ANGEL_PASSWORD, Config.ANGEL_TOTP_SECRET]):
            raise RuntimeError("Missing Angel One credentials in .env")

        self.smart_api = SmartConnect(api_key=Config.ANGEL_API_KEY)
        totp = pyotp.TOTP(Config.ANGEL_TOTP_SECRET).now()
        try:
            data = self.smart_api.generateSession(
                Config.ANGEL_CLIENT_ID, Config.ANGEL_PASSWORD, totp)
            if not data.get("status"):
                log.error(f"Login failed: {data}")
                return False
            self._logged_in = True
            log.info("Logged into Angel One successfully")
            return True
        except Exception as e:
            log.error(f"Login exception: {e}")
            return False

    def ensure_logged_in(self):
        if not self._logged_in:
            self.login()

    def get_candles(self, symbol_token: str, exchange: str,
                    interval: str, from_date: str, to_date: str,
                    retries: int = 3) -> pd.DataFrame:
        """
        Fetch OHLCV candles with automatic retry on failure.
        from_date / to_date format: 'YYYY-MM-DD HH:MM'
        interval: ONE_MINUTE | FIVE_MINUTE | FIFTEEN_MINUTE | ONE_DAY
        """
        self.ensure_logged_in()
        params = {"exchange": exchange, "symboltoken": symbol_token,
                  "interval": interval, "fromdate": from_date, "todate": to_date}

        for attempt in range(retries):
            try:
                resp = self.smart_api.getCandleData(params)
                if not resp.get("status"):
                    log.warning(f"Candle fetch attempt {attempt+1} failed: {resp}")
                    time.sleep(2)
                    continue
                df = pd.DataFrame(resp["data"],
                                  columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df[["open","high","low","close","volume"]] = \
                    df[["open","high","low","close","volume"]].apply(pd.to_numeric)
                return df
            except Exception as e:
                log.error(f"Candle fetch exception attempt {attempt+1}: {e}")
                time.sleep(3)
        return pd.DataFrame()

    def get_option_chain(self, expiry: str, strike_price: int) -> dict:
        """
        Fetch Nifty option chain for a given expiry and around a strike range.
        expiry format: '30JUN2026'
        Returns raw response dict from Angel One.
        """
        self.ensure_logged_in()
        try:
            resp = self.smart_api.getOptionChain(
                name="NIFTY", expirydate=expiry, strikePrice=strike_price)
            if resp.get("status"):
                return resp.get("data", {})
            log.warning(f"Option chain fetch failed: {resp}")
            return {}
        except Exception as e:
            log.error(f"Option chain exception: {e}")
            return {}

    def get_ltp(self, exchange: str, symbol: str, token: str) -> float | None:
        """Get last traded price for any instrument."""
        self.ensure_logged_in()
        try:
            resp = self.smart_api.ltpData(exchange, symbol, token)
            if resp.get("status"):
                return float(resp["data"]["ltp"])
            return None
        except Exception as e:
            log.error(f"LTP fetch exception: {e}")
            return None

    def place_order(self, trading_symbol: str, token: str, exchange: str,
                    transaction_type: str, quantity: int,
                    order_type: str = "MARKET", price: float = 0) -> dict | None:
        """
        Place a real order on Angel One.
        transaction_type: BUY | SELL
        ONLY called by live_trader.py -- never by backtest or paper modules.
        """
        self.ensure_logged_in()
        params = {
            "variety": "NORMAL",
            "tradingsymbol": trading_symbol,
            "symboltoken": token,
            "transactiontype": transaction_type,
            "exchange": exchange,
            "ordertype": order_type,
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": price,
            "quantity": quantity,
        }
        try:
            resp = self.smart_api.placeOrder(params)
            log.info(f"Order placed: {resp}")
            return resp
        except Exception as e:
            log.error(f"Order placement failed: {e}")
            return None
