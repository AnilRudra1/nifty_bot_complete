"""
Instrument selector. Runs every morning at 9:00 AM before market opens.
Automatically finds the best Nifty option strikes to watch for the day.

Logic:
1. Get current Nifty spot price
2. Find this week's expiry date (nearest Thursday)
3. Pull option chain for strikes within STRIKE_RANGE_POINTS of spot
4. Filter by minimum OI (liquidity filter)
5. Score each strike by OI, volume, IV, proximity to spot
6. Return top N CE and PE strikes as the day's active watchlist
"""

from datetime import datetime, timedelta
from config import Config
from utils.logger import get_logger

log = get_logger("instrument_selector")

# Nifty spot index token on Angel One (NSE)
NIFTY_SPOT_TOKEN = "99926000"
NIFTY_EXCHANGE   = "NSE"
NIFTY_FUT_EXCHANGE = "NFO"


def get_nearest_thursday(from_date: datetime = None) -> datetime:
    """Return the nearest upcoming Thursday (weekly expiry day)."""
    d = from_date or datetime.now()
    days_ahead = (3 - d.weekday()) % 7   # Thursday = weekday 3
    if days_ahead == 0 and d.hour >= 15:  # today is Thursday but market closed
        days_ahead = 7
    return (d + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0)


def format_expiry_str(dt: datetime) -> str:
    """Returns expiry string in Angel One format e.g. '26JUN2026'."""
    return dt.strftime("%d%b%Y").upper()


def round_to_strike(price: float, step: int = 50) -> int:
    """Round spot price to nearest valid Nifty strike (multiples of 50)."""
    return int(round(price / step) * step)


def score_strike(oi: float, volume: float, proximity_pts: float) -> float:
    """
    Score a single strike out of 100.
    Higher OI = more liquidity = better.
    Higher volume = more active = better.
    Closer to spot = more sensitive premium movement = better.
    """
    oi_score        = min(oi / 1_000_000, 40)          # max 40 points from OI
    volume_score    = min(volume / 100_000, 30)         # max 30 points from volume
    proximity_score = max(0, 30 - proximity_pts / 20)   # max 30 points, decays with distance
    return round(oi_score + volume_score + proximity_score, 2)


def select_instruments(client, top_n: int = 5) -> dict:
    """
    Main function called every morning.
    Returns dict: { 'expiry': str, 'ce_strikes': [...], 'pe_strikes': [...] }
    Each strike entry: { symbol, token, exchange, strike, option_type, score }
    """
    # Step 1: Get Nifty spot LTP
    spot = client.get_ltp(NIFTY_EXCHANGE, "Nifty 50", NIFTY_SPOT_TOKEN)
    if not spot:
        log.error("Could not fetch Nifty spot price for instrument selection")
        return {}

    log.info(f"Nifty spot: {spot}")
    atm_strike = round_to_strike(spot)
    expiry_dt  = get_nearest_thursday()
    expiry_str = format_expiry_str(expiry_dt)
    log.info(f"Expiry: {expiry_str}, ATM strike: {atm_strike}")

    # Step 2: Build list of strikes to evaluate
    strike_step = 50
    strike_range = Config.STRIKE_RANGE_POINTS
    strikes = list(range(atm_strike - strike_range,
                         atm_strike + strike_range + strike_step,
                         strike_step))

    # Step 3: Fetch option chain
    chain_data = client.get_option_chain(expiry_str, atm_strike)
    if not chain_data:
        log.warning("Option chain empty, falling back to ATM ±5 strikes only")
        chain_data = {}

    # Step 4: Score each strike for CE and PE
    ce_candidates = []
    pe_candidates = []

    for strike in strikes:
        proximity = abs(strike - spot)

        # Try to pull OI/volume from option chain response
        # Angel One option chain structure: chain_data is a list of dicts
        ce_info = _find_in_chain(chain_data, strike, "CE", expiry_str)
        pe_info = _find_in_chain(chain_data, strike, "PE", expiry_str)

        if ce_info:
            oi, vol = ce_info.get("openInterest", 0), ce_info.get("totalTradedVolume", 0)
            if oi >= Config.MIN_OI_THRESHOLD:
                score = score_strike(oi, vol, proximity)
                ce_candidates.append({
                    "symbol": ce_info.get("tradingSymbol", f"NIFTY{expiry_str}{strike}CE"),
                    "token":  ce_info.get("symbolToken", ""),
                    "exchange": NIFTY_FUT_EXCHANGE,
                    "strike": strike,
                    "option_type": "CE",
                    "oi": oi,
                    "volume": vol,
                    "score": score,
                })

        if pe_info:
            oi, vol = pe_info.get("openInterest", 0), pe_info.get("totalTradedVolume", 0)
            if oi >= Config.MIN_OI_THRESHOLD:
                score = score_strike(oi, vol, proximity)
                pe_candidates.append({
                    "symbol": pe_info.get("tradingSymbol", f"NIFTY{expiry_str}{strike}PE"),
                    "token":  pe_info.get("symbolToken", ""),
                    "exchange": NIFTY_FUT_EXCHANGE,
                    "strike": strike,
                    "option_type": "PE",
                    "oi": oi,
                    "volume": vol,
                    "score": score,
                })

    # If chain was empty (common before market opens), fall back to ATM ±5 strikes
    if not ce_candidates and not pe_candidates:
        log.warning("No option chain data. Using ATM ±5 strikes as fallback watchlist.")
        for strike in [atm_strike + i * 50 for i in range(-5, 6)]:
            for opt in ["CE", "PE"]:
                entry = {
                    "symbol": f"NIFTY{expiry_str}{strike}{opt}",
                    "token": "",
                    "exchange": NIFTY_FUT_EXCHANGE,
                    "strike": strike,
                    "option_type": opt,
                    "oi": 0,
                    "volume": 0,
                    "score": max(0, 30 - abs(strike - spot) / 20),
                }
                if opt == "CE":
                    ce_candidates.append(entry)
                else:
                    pe_candidates.append(entry)

    # Step 5: Sort by score and take top N
    top_ce = sorted(ce_candidates, key=lambda x: x["score"], reverse=True)[:top_n]
    top_pe = sorted(pe_candidates, key=lambda x: x["score"], reverse=True)[:top_n]

    log.info(f"Selected {len(top_ce)} CE and {len(top_pe)} PE strikes")
    for s in top_ce + top_pe:
        log.info(f"  {s['symbol']} | OI: {s['oi']:,} | Score: {s['score']}")

    return {
        "expiry": expiry_str,
        "spot":   spot,
        "atm":    atm_strike,
        "ce_strikes": top_ce,
        "pe_strikes": top_pe,
        "selected_at": datetime.now().isoformat(),
    }


def _find_in_chain(chain_data, strike: int, option_type: str, expiry: str) -> dict:
    """Search option chain response for a specific strike + option type."""
    if isinstance(chain_data, list):
        for item in chain_data:
            if (item.get("strikePrice") == strike
                    and item.get("optionType", "").upper() == option_type):
                return item
    return {}
