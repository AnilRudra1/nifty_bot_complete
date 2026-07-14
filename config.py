"""
Central configuration. Every module imports from here.
All values come from .env so you never hardcode credentials.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Angel One ──────────────────────────────────────────────────────────────
    ANGEL_API_KEY        = os.getenv("ANGEL_API_KEY", "")
    ANGEL_CLIENT_ID      = os.getenv("ANGEL_CLIENT_ID", "")
    ANGEL_PASSWORD       = os.getenv("ANGEL_PASSWORD", "")
    ANGEL_TOTP_SECRET    = os.getenv("ANGEL_TOTP_SECRET", "")

    # ── Telegram ───────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Mode ───────────────────────────────────────────────────────────────────
    TRADING_MODE         = os.getenv("TRADING_MODE", "paper")

    # ── Capital & Risk ─────────────────────────────────────────────────────────
    CAPITAL              = float(os.getenv("CAPITAL", 100000))
    RISK_PER_TRADE_PCT   = float(os.getenv("RISK_PER_TRADE_PCT", 1.5))
    MAX_LOSS_PER_DAY     = float(os.getenv("MAX_LOSS_PER_DAY", 999999))   # disabled for testing
    MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", 9999))     # disabled for testing
    LOT_SIZE             = int(os.getenv("LOT_SIZE", 65))

    # ── Dead stock filters ─────────────────────────────────────────────────────
    MIN_PREMIUM          = float(os.getenv("MIN_PREMIUM", 8.0))     # skip options below ₹8
    MIN_VOLUME           = int(os.getenv("MIN_VOLUME", 0))           # min volume (0 = off)
    EXPIRY_NO_TRADE_HOUR = int(os.getenv("EXPIRY_NO_TRADE_HOUR", 14)) # no new trades after 2PM on expiry

    # ── Strategy ───────────────────────────────────────────────────────────────
    TIMEFRAME            = os.getenv("TIMEFRAME", "FIVE_MINUTE")
    STRIKE_RANGE_POINTS  = int(os.getenv("STRIKE_RANGE_POINTS", 500))
    MIN_OI_THRESHOLD     = int(os.getenv("MIN_OI_THRESHOLD", 100000))
    ATR_TRAIL_MULTIPLIER = float(os.getenv("ATR_TRAIL_MULTIPLIER", 1.0))

    # ── Market timings (IST, 24hr) ─────────────────────────────────────────────
    MARKET_OPEN          = "09:15"
    MARKET_CLOSE         = "15:30"
    NO_ENTRY_AFTER       = "15:15"
    SQUARE_OFF_TIME      = "15:15"
    AVOID_OPEN_MINUTES   = 15
    AVOID_CLOSE_MINUTES  = 15

    # ── Indicator settings ─────────────────────────────────────────────────────
    RSI_PERIOD           = 14
    RSI_OVERSOLD         = 40
    RSI_OVERBOUGHT       = 60
    EMA_FAST             = 9
    EMA_SLOW             = 21
    ADX_PERIOD           = 14
    ADX_TREND_THRESHOLD  = 20
    ATR_PERIOD           = 14
    VOLUME_SURGE_MULT    = 1.5
    SR_LOOKBACK          = 5
    SR_TOLERANCE_PCT     = 0.15

    # ── API rate limit settings ────────────────────────────────────────────────
    API_DELAY_BETWEEN    = float(os.getenv("API_DELAY_BETWEEN", 12))  # seconds between instruments
    API_RETRY_DELAY      = float(os.getenv("API_RETRY_DELAY", 20))    # seconds between retries
    API_MAX_RETRIES      = int(os.getenv("API_MAX_RETRIES", 2))       # max retries per fetch
    POLL_SECONDS         = int(os.getenv("POLL_SECONDS", 30))         # cycle wait

    # ── Dashboard ──────────────────────────────────────────────────────────────
    DASHBOARD_PORT       = int(os.getenv("DASHBOARD_PORT", 5000))
    DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "dev_secret_change_me")

    # ── Paths ──────────────────────────────────────────────────────────────────
    LOG_DIR              = "logs"
    TRADE_LOG_PATH       = "logs/trades.csv"
    DETAILED_LOG_PATH    = "logs/trade_details.json"
    ERROR_LOG_PATH       = "logs/errors.log"
    STATE_FILE           = "logs/bot_state.json"

