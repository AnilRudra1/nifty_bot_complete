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
    log.warning("smartapi-python not installed")


class AngelOneClient:
    def __init__(self):
        self.smart_api  = None
        self._logged_in = False

    def login(self) -> bool:
        if SmartConnect is None:
            raise RuntimeError("Run: pip install smartapi-python")
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

    def get_candles(self, symbol_token, exchange, interval,
                    from_date, to_date, retries=2) -> pd.DataFrame:
        if not symbol_token:
            log.error("Empty token passed to get_candles")
            return pd.DataFrame()

        params = {
            "exchange":    exchange,
            "symboltoken": symbol_token,
            "interval":    interval,
            "fromdate":    from_date,
            "todate":      to_date,
        }

        for attempt in range(retries):
            try:
                resp = self.smart_api.getCandleData(params)
                if not resp.get("status"):
                    log.warning(f"Candle fetch attempt {attempt+1} failed: {resp}")
                    time.sleep(Config.API_DELAY)
                    continue
                df = pd.DataFrame(
                    resp["data"],
                    columns=["timestamp","open","high","low","close","volume"]
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                for c in ["open","high","low","close","volume"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                return df
            except Exception as e:
                log.error(f"Candle fetch exception attempt {attempt+1}: {e}")
                time.sleep(Config.API_DELAY)

        return pd.DataFrame()

    def get_ltp(self, exchange, symbol, token) -> float:
        try:
            resp = self.smart_api.ltpData(exchange, symbol, token)
            if resp.get("status"):
                return float(resp["data"]["ltp"])
            return None
        except Exception as e:
            log.error(f"LTP error: {e}")
            return None

    def place_order(self, trading_symbol, token, exchange,
                    transaction_type, quantity,
                    order_type="MARKET", price=0) -> dict:
        params = {
            "variety":         "NORMAL",
            "tradingsymbol":   trading_symbol,
            "symboltoken":     token,
            "transactiontype": transaction_type,
            "exchange":        exchange,
            "ordertype":       order_type,
            "producttype":     "INTRADAY",
            "duration":        "DAY",
            "price":           price,
            "quantity":        quantity,
        }
        try:
            resp = self.smart_api.placeOrder(params)
            log.info(f"Order placed: {resp}")
            return resp
        except Exception as e:
            log.error(f"Order failed: {e}")
            return None
