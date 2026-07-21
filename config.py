import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    # Angel One
    ANGEL_API_KEY        = os.getenv("ANGEL_API_KEY", "")
    ANGEL_CLIENT_ID      = os.getenv("ANGEL_CLIENT_ID", "")
    ANGEL_PASSWORD       = os.getenv("ANGEL_PASSWORD", "")
    ANGEL_TOTP_SECRET    = os.getenv("ANGEL_TOTP_SECRET", "")

    # Telegram
    TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID", "")

    # Mode
    TRADING_MODE         = os.getenv("TRADING_MODE", "paper")

    # Capital
    CAPITAL              = float(os.getenv("CAPITAL", 100000))
    LOT_SIZE             = int(os.getenv("LOT_SIZE", 75))
    FIXED_LOTS           = int(os.getenv("FIXED_LOTS", 2))

    # Limits — set very high for testing
    MAX_LOSS_PER_DAY     = float(os.getenv("MAX_LOSS_PER_DAY", 999999))
    MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", 9999))

    # Dead stock filter
    MIN_PREMIUM          = float(os.getenv("MIN_PREMIUM", 8.0))
    EXPIRY_CUTOFF_HOUR   = int(os.getenv("EXPIRY_CUTOFF_HOUR", 14))

    # Strategy
    TIMEFRAME            = os.getenv("TIMEFRAME", "FIVE_MINUTE")
    STRIKE_RANGE_POINTS  = int(os.getenv("STRIKE_RANGE_POINTS", 500))
    ATR_TRAIL_MULTIPLIER = float(os.getenv("ATR_TRAIL_MULTIPLIER", 1.0))
    SIGNAL_SCORE_MIN     = int(os.getenv("SIGNAL_SCORE_MIN", 65))

    # Market timings
    AVOID_OPEN_MINUTES   = 15
    SQUARE_OFF_HOUR      = 15
    SQUARE_OFF_MINUTE    = 15

    # Indicators
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

    # API pacing — generous to avoid rate limits
    API_DELAY            = float(os.getenv("API_DELAY", 15))
    POLL_SECONDS         = int(os.getenv("POLL_SECONDS", 60))

    # Dashboard
    DASHBOARD_PORT       = int(os.getenv("DASHBOARD_PORT", 5000))
    DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "changeme")

    # Paths
    LOG_DIR              = "logs"
    TRADE_LOG_PATH       = "logs/trades.csv"
    ERROR_LOG_PATH       = "logs/errors.log"
    STATE_FILE           = "logs/bot_state.json"
