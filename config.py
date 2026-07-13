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
    TRADING_MODE         = os.getenv("TRADING_MODE", "paper")   # paper | live

    # ── Capital & Risk ─────────────────────────────────────────────────────────
    CAPITAL              = float(os.getenv("CAPITAL", 100000))
    RISK_PER_TRADE_PCT   = float(os.getenv("RISK_PER_TRADE_PCT", 1.5))
    MAX_LOSS_PER_DAY     = float(os.getenv("MAX_LOSS_PER_DAY", 5000))
    MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", 6))
    LOT_SIZE             = int(os.getenv("LOT_SIZE", 50))

    # ── Strategy ───────────────────────────────────────────────────────────────
    TIMEFRAME            = os.getenv("TIMEFRAME", "FIVE_MINUTE")
    STRIKE_RANGE_POINTS  = int(os.getenv("STRIKE_RANGE_POINTS", 500))
    MIN_OI_THRESHOLD     = int(os.getenv("MIN_OI_THRESHOLD", 100000))
    ATR_TRAIL_MULTIPLIER = float(os.getenv("ATR_TRAIL_MULTIPLIER", 1.5))

    # ── Market timings (IST, 24hr) ─────────────────────────────────────────────
    MARKET_OPEN          = "09:15"
    MARKET_CLOSE         = "15:30"
    NO_ENTRY_AFTER       = "15:15"   # no new entries after this
    SQUARE_OFF_TIME      = "15:15"   # force close all positions
    AVOID_OPEN_MINUTES   = 15        # skip first 15 min after open
    AVOID_CLOSE_MINUTES  = 15        # skip last 15 min before close

    # ── Indicator settings ─────────────────────────────────────────────────────
    RSI_PERIOD           = 14
    RSI_OVERSOLD         = 40
    RSI_OVERBOUGHT       = 60
    EMA_FAST             = 9
    EMA_SLOW             = 21
    ADX_PERIOD           = 14
    ADX_TREND_THRESHOLD  = 20        # ADX above this = trending market
    ATR_PERIOD           = 14
    VOLUME_SURGE_MULT    = 1.5       # volume must be 1.5x avg to confirm signal
    SR_LOOKBACK          = 5
    SR_TOLERANCE_PCT     = 0.15

    # ── Dashboard ──────────────────────────────────────────────────────────────
    DASHBOARD_PORT       = int(os.getenv("DASHBOARD_PORT", 5000))
    DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "dev_secret_change_me")

    # ── Paths ──────────────────────────────────────────────────────────────────
    LOG_DIR              = "logs"
    TRADE_LOG_PATH       = "logs/trades.csv"
    ERROR_LOG_PATH       = "logs/errors.log"
    STATE_FILE           = "logs/bot_state.json"
