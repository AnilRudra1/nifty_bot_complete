import requests
from datetime import datetime
from config import Config
from utils.logger import get_logger

log = get_logger("telegram")

def _send(msg):
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

def notify_signal(symbol, direction, score, reason, price):
    emoji = "🟢" if direction == "BUY" else "🔴"
    _send(f"{emoji} *SIGNAL*\n`{symbol}`\n{direction} | Score:{score}\n₹{price}\n{reason}")

def notify_entry(symbol, direction, entry, sl, target, qty):
    emoji = "📈" if direction == "BUY" else "📉"
    _send(f"{emoji} *ENTRY*\n`{symbol}`\n{direction} @ ₹{entry}\nSL: ₹{sl} | Qty:{qty}\n{datetime.now().strftime('%H:%M:%S')}")

def notify_exit(symbol, direction, entry, exit_price, pnl, reason):
    emoji = "✅" if pnl > 0 else "❌"
    _send(f"{emoji} *EXIT* {reason}\n`{symbol}`\nEntry:₹{entry} Exit:₹{exit_price}\nP&L: ₹{pnl:+,.0f}")

def notify_sl_trail(symbol, old_sl, new_sl, price):
    _send(f"🔁 *TRAIL SL* `{symbol}`\n{old_sl} → {new_sl} | Price:₹{price}")

def notify_error(msg):
    _send(f"⚠️ *ERROR*\n{msg}")

def notify_bot_started(mode):
    _send(f"🚀 *Bot Started* — {mode.upper()}\n{datetime.now().strftime('%d %b %Y %H:%M')}")

def notify_bot_stopped(reason="manual"):
    _send(f"🛑 *Bot Stopped* — {reason}")
