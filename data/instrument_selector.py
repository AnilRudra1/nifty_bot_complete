import requests
import json
from datetime import datetime, timedelta
from config import Config
from utils.logger import get_logger

log = get_logger("instrument_selector")

NIFTY_SPOT_TOKEN  = "99926000"
NIFTY_SPOT_SYMBOL = "Nifty 50"
NIFTY_EXCHANGE    = "NSE"
NFO_EXCHANGE      = "NFO"
SCRIP_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

def download_scrip_master():
    log.info("Downloading scrip master...")
    resp = requests.get(SCRIP_URL, timeout=30)
    data = resp.json()
    log.info(f"Scrip master downloaded: {len(data)} instruments")
    return data

def get_nearest_expiry(data):
    today = datetime.now().date()
    expiries = sorted(set(
        x.get("expiry") for x in data
        if x.get("name") == "NIFTY"
        and x.get("instrumenttype") == "OPTIDX"
        and x.get("expiry")
    ))
    upcoming = []
    for e in expiries:
        try:
            dt = datetime.strptime(e, "%d%b%Y").date()
            if dt >= today:
                upcoming.append((dt, e))
        except:
            continue
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x[0])
    return upcoming[0][1]

def parse_strike(s):
    try:
        return float(s) / 100.0
    except:
        return 0.0

def score_strike(proximity):
    return max(0, round(100 - proximity / 10, 1))

def select_instruments(client, top_n=5):
    # Get spot price
    spot = client.get_ltp(NIFTY_EXCHANGE, NIFTY_SPOT_SYMBOL, NIFTY_SPOT_TOKEN)
    if not spot:
        log.error("Could not fetch Nifty spot price")
        return {}
    log.info(f"Nifty spot: {spot}")

    # Download scrip master
    try:
        data = download_scrip_master()
    except Exception as e:
        log.error(f"Scrip master failed: {e}")
        return {}

    # Get nearest expiry
    expiry_str = get_nearest_expiry(data)
    if not expiry_str:
        log.error("No upcoming expiry found")
        return {}
    log.info(f"Target expiry: {expiry_str}")

    # Filter Nifty options for this expiry
    options = [
        x for x in data
        if x.get("name") == "NIFTY"
        and x.get("instrumenttype") == "OPTIDX"
        and x.get("expiry") == expiry_str
        and x.get("symbol")
        and x.get("token")
    ]
    log.info(f"Found {len(options)} Nifty options for {expiry_str}")

    if not options:
        log.error("No options found")
        return {}

    # Update lot size from scrip master
    if options:
        try:
            Config.LOT_SIZE = int(options[0].get("lotsize", Config.LOT_SIZE))
            log.info(f"Lot size updated to {Config.LOT_SIZE}")
        except:
            pass

    # Score and separate CE/PE
    ce_list, pe_list = [], []
    for opt in options:
        strike    = parse_strike(opt.get("strike", "0"))
        proximity = abs(strike - spot)
        if proximity > Config.STRIKE_RANGE_POINTS:
            continue
        symbol = opt.get("symbol", "")
        token  = opt.get("token", "")
        if not token:
            continue
        entry = {
            "symbol":      symbol,
            "token":       token,
            "exchange":    NFO_EXCHANGE,
            "strike":      strike,
            "lot_size":    int(opt.get("lotsize", Config.LOT_SIZE)),
            "option_type": "CE" if symbol.endswith("CE") else "PE",
            "expiry":      expiry_str,
            "score":       score_strike(proximity),
        }
        if symbol.endswith("CE"):
            ce_list.append(entry)
        elif symbol.endswith("PE"):
            pe_list.append(entry)

    top_ce = sorted(ce_list, key=lambda x: x["score"], reverse=True)[:top_n]
    top_pe = sorted(pe_list, key=lambda x: x["score"], reverse=True)[:top_n]

    log.info(f"Selected {len(top_ce)} CE and {len(top_pe)} PE strikes:")
    for s in top_ce + top_pe:
        log.info(f"  {s['symbol']} | Token:{s['token']} | Strike:{s['strike']} | Score:{s['score']}")

    return {
        "expiry":      expiry_str,
        "spot":        spot,
        "ce_strikes":  top_ce,
        "pe_strikes":  top_pe,
        "selected_at": datetime.now().isoformat(),
    }
