"""
Telegram notifications. Sends you a message on your phone for every important event:
  - Signal detected
  - Trade entered / exited
  - Stop loss hit / target hit
  - Daily P&L summary
  - Bot error / bot stopped

Setup:
1. Create a Telegram bot: message @BotFather on Telegram, use /newbot
2. Copy the bot token into TELEGRAM_BOT_TOKEN in .env
3. Start a chat with your new bot, then get your chat ID by visiting:
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
4. Copy the chat_id number into TELEGRAM_CHAT_ID in .env
"""

import requests
from datetime import datetime
from config import Config
from utils.logger import get_logger

log = get_logger("telegram")

BASE_URL = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"


def _send(message: str, parse_mode: str = "Markdown") -> bool:
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        log.debug("Telegram not configured, skipping notification")
        return False
    try:
        resp = requests.post(BASE_URL, json={
            "chat_id": Config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode,
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def notify_signal(symbol: str, direction: str, score: int, reason: str, price: float):
    emoji = "🟢" if direction == "BUY" else "🔴"
    _send(
        f"{emoji} *SIGNAL DETECTED*\n"
        f"Symbol : `{symbol}`\n"
        f"Direction : *{direction}*\n"
        f"Score : {score}/100\n"
        f"Reason : {reason}\n"
        f"Price : ₹{price:,.2f}\n"
        f"Time : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_entry(symbol: str, direction: str, entry: float,
                 sl: float, target: float, qty: int):
    emoji = "📈" if direction == "BUY" else "📉"
    _send(
        f"{emoji} *TRADE ENTERED*\n"
        f"Symbol : `{symbol}`\n"
        f"Direction : *{direction}*\n"
        f"Entry : ₹{entry:,.2f}\n"
        f"Stop Loss : ₹{sl:,.2f}\n"
        f"Target : ₹{target:,.2f}\n"
        f"Qty : {qty}\n"
        f"Time : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_exit(symbol: str, direction: str, entry: float,
                exit_price: float, pnl: float, reason: str):
    emoji = "✅" if pnl > 0 else "❌"
    _send(
        f"{emoji} *TRADE CLOSED*\n"
        f"Symbol : `{symbol}`\n"
        f"Direction : *{direction}*\n"
        f"Entry : ₹{entry:,.2f}\n"
        f"Exit : ₹{exit_price:,.2f}\n"
        f"P&L : ₹{pnl:+,.2f}\n"
        f"Reason : {reason}\n"
        f"Time : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_sl_trail(symbol: str, old_sl: float, new_sl: float, current_price: float):
    _send(
        f"🔁 *TRAILING SL UPDATED*\n"
        f"Symbol : `{symbol}`\n"
        f"Old SL : ₹{old_sl:,.2f} → New SL : ₹{new_sl:,.2f}\n"
        f"Current Price : ₹{current_price:,.2f}"
    )


def notify_daily_summary(trades: int, wins: int, losses: int,
                         total_pnl: float, win_rate: float):
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    _send(
        f"{emoji} *DAILY SUMMARY*\n"
        f"Date : {datetime.now().strftime('%d %b %Y')}\n"
        f"Total Trades : {trades}\n"
        f"Wins : {wins} | Losses : {losses}\n"
        f"Win Rate : {win_rate:.1f}%\n"
        f"Total P&L : ₹{total_pnl:+,.2f}"
    )


def notify_error(error_msg: str):
    _send(f"⚠️ *BOT ERROR*\n`{error_msg}`\n{datetime.now().strftime('%H:%M:%S')}")


def notify_bot_started(mode: str):
    _send(f"🚀 *Bot Started* in *{mode.upper()}* mode\n{datetime.now().strftime('%d %b %Y %H:%M:%S')}")


def notify_bot_stopped(reason: str = "manual"):
    _send(f"🛑 *Bot Stopped* — {reason}\n{datetime.now().strftime('%H:%M:%S')}")


def notify_daily_limit_hit(limit_type: str, value: float):
    _send(
        f"🚫 *DAILY LIMIT HIT*\n"
        f"Type : {limit_type}\n"
        f"Value : ₹{value:,.2f}\n"
        f"Bot has stopped trading for today."
    )
