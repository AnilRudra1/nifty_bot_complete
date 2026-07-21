import argparse
import threading
import os
from config import Config
from utils.logger import get_logger

log = get_logger("main")

def run_backtest(csv_path):
    from backtest.backtest_engine import run_backtest_from_csv
    run_backtest_from_csv(csv_path)

def run_paper_or_live(mode):
    from broker.angelone_client import AngelOneClient
    from data.instrument_selector import select_instruments

    client = AngelOneClient()
    if not client.login():
        log.error("Login failed")
        return

    log.info("Selecting instruments...")
    selection = select_instruments(client, top_n=5)
    if not selection:
        log.error("Instrument selection failed")
        return

    instruments = selection.get("ce_strikes", []) + selection.get("pe_strikes", [])
    log.info(f"Watching {len(instruments)} strikes")

    if mode == "paper":
        from execution.paper_trader import PaperTrader
        bot = PaperTrader(instruments=instruments)
    else:
        from execution.live_trader import LiveTrader
        bot = LiveTrader(instruments=instruments)

    try:
        from dashboard.app import run_dashboard
        dash_thread = threading.Thread(
            target=run_dashboard, kwargs={"bot_ref": bot}, daemon=True)
        dash_thread.start()
        log.info(f"Dashboard → http://0.0.0.0:{Config.DASHBOARD_PORT}")
    except Exception as e:
        log.warning(f"Dashboard failed: {e}")

    bot.run()

def main():
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["paper","live","backtest"], default="paper")
    parser.add_argument("--csv", default="data/nifty_5min_sample.csv")
    args = parser.parse_args()
    log.info(f"Starting | Mode: {args.mode.upper()}")
    # Wait if started during 9:15-9:20 rush hour
    from datetime import datetime, time as dtime
    import time as ttime
    now = datetime.now().time()
    if dtime(9, 14) <= now <= dtime(9, 21):
        log.info("Market just opened — waiting 5 min for API to stabilise...")
        ttime.sleep(300)
    if args.mode == "backtest":
        run_backtest(args.csv)
    else:
        run_paper_or_live(args.mode)

if __name__ == "__main__":
    main()
