"""
Main entry point for the Nifty bot.

Usage:
    python main.py --mode paper      # paper trading (default)
    python main.py --mode backtest   # backtest on a CSV
    python main.py --mode live       # real trading (only when ready)

Options:
    --csv PATH    CSV file for backtest mode (required when mode=backtest)
    --no-dash     Skip starting the dashboard (useful for headless backtest)
    --walk        Enable walk-forward split for backtest (70% train / 30% validate)

EC2 setup:
    1. pip install -r requirements.txt --break-system-packages
    2. cp .env.example .env && nano .env   (fill in your credentials)
    3. python main.py --mode paper
    4. Open browser: http://YOUR_EC2_PUBLIC_IP:5000
       (Make sure port 5000 is open in EC2 Security Group inbound rules)
    5. Check Telegram for startup message

To run in background on EC2 (so it keeps running after you close SSH):
    nohup python main.py --mode paper > logs/stdout.log 2>&1 &
    tail -f logs/stdout.log    # watch live output

To stop background process:
    ps aux | grep main.py     # find the process ID
    kill <PID>
"""

import argparse
import threading
import os
from config import Config
from utils.logger import get_logger

log = get_logger("main")


def run_backtest(csv_path: str, walk_forward: bool):
    from backtest.backtest_engine import run_backtest_from_csv
    split = 0.7 if walk_forward else None
    run_backtest_from_csv(csv_path, walk_forward_split=split)


def run_paper_or_live(mode: str):
    from broker.angelone_client import AngelOneClient
    from data.instrument_selector import select_instruments

    client = AngelOneClient()
    if not client.login():
        log.error("Login failed — check credentials in .env")
        return

    log.info("Selecting today's Nifty instruments...")
    selection = select_instruments(client, top_n=5)
    if not selection:
        log.error("Instrument selection failed")
        return

    instruments = selection.get("ce_strikes", []) + selection.get("pe_strikes", [])
    log.info(f"Watching {len(instruments)} strikes for today")

    if mode == "paper":
        from execution.paper_trader import PaperTrader
        bot = PaperTrader(instruments=instruments)
    else:
        from execution.live_trader import LiveTrader
        bot = LiveTrader(instruments=instruments)

    # Start dashboard in a separate thread
    try:
        from dashboard.app import run_dashboard
        dash_thread = threading.Thread(
            target=run_dashboard, kwargs={"bot_ref": bot}, daemon=True)
        dash_thread.start()
        log.info(f"Dashboard running → http://0.0.0.0:{Config.DASHBOARD_PORT}")
    except Exception as e:
        log.warning(f"Dashboard failed to start: {e}")

    # Run bot in main thread
    bot.run()


def main():
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    parser = argparse.ArgumentParser(description="Nifty F&O trading bot")
    parser.add_argument("--mode",    choices=["paper", "live", "backtest"], default="paper")
    parser.add_argument("--csv",     default="data/nifty_5min_sample.csv", help="CSV for backtest")
    parser.add_argument("--walk",    action="store_true", help="Walk-forward backtest")
    parser.add_argument("--no-dash", action="store_true", help="Skip dashboard")
    args = parser.parse_args()

    log.info(f"Starting Nifty Bot | Mode: {args.mode.upper()}")

    if args.mode == "backtest":
        run_backtest(args.csv, args.walk)
    else:
        run_paper_or_live(args.mode)


if __name__ == "__main__":
    main()
