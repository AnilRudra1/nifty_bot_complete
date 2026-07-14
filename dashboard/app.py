"""
Web dashboard. Access from browser at http://YOUR_EC2_IP:5000

Shows: bot status, current positions, live P&L, trade history, controls.
Uses Flask-SocketIO to push live updates to the browser every 5 seconds.

To open EC2 port 5000:
  AWS Console → EC2 → Security Groups → Inbound Rules → Add Rule
  Type: Custom TCP | Port: 5000 | Source: My IP (or 0.0.0.0/0 for anywhere)
"""

import os
import json
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from config import Config
from utils.heartbeat import read_state, is_alive
from utils.logger import get_logger

log = get_logger("dashboard")

app   = Flask(__name__)
app.secret_key = Config.DASHBOARD_SECRET_KEY
io    = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Shared bot reference (set by main.py after starting bot thread)
_bot_ref = None

def set_bot_ref(bot):
    global _bot_ref
    _bot_ref = bot


def _load_trades() -> list:
    try:
        if os.path.exists(Config.TRADE_LOG_PATH):
            df = pd.read_csv(Config.TRADE_LOG_PATH)
            if "exit_time" in df.columns:
                df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
                today = pd.Timestamp.now().date()
                df = df[df["exit_time"].dt.date == today]
            # Convert all timestamps to strings so JSON serialization works
            for col in df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
                df[col] = df[col].astype(str)
            return df.to_dict("records")
    except Exception as e:
        log.error(f"Trade load error: {e}")
    return []


def _dashboard_data() -> dict:
    state  = read_state()
    trades = _load_trades()
    wins   = [t for t in trades if t.get("pnl_rupees", 0) > 0]
    total_pnl = sum(t.get("pnl_rupees", 0) for t in trades)
    positions = {}
    if _bot_ref:
        positions = {}
    if _bot_ref:
        for k, v in _bot_ref.positions.items():
            entry = v.get("entry", 0)
            last  = v.get("last_price", entry)
            sl    = v.get("sl", 0)
            direction = v.get("direction", "BUY")
            unreal_pnl = round(
                (last - entry) * v.get("qty", 130) if direction == "BUY"
                else (entry - last) * v.get("qty", 130), 2
            )
            positions[k] = {
                **v,
                "entry_time":    str(v.get("entry_time", "")),
                "last_price":    last,
                "current_sl":    round(sl, 2),
                "unrealised_pnl": unreal_pnl,
            }

    return {
        "alive":        is_alive(),
        "status":       state.get("status", "unknown"),
        "mode":         state.get("mode", Config.TRADING_MODE),
        "last_beat":    state.get("last_heartbeat", "—"),
        "daily_pnl":    state.get("daily_pnl", 0),
        "trades_today": state.get("trades_today", 0),
        "instruments":  state.get("instruments", []),
        "positions":    positions,
        "total_trades": len(trades),
        "wins":         len(wins),
        "losses":       len(trades) - len(wins),
        "win_rate":     round(len(wins)/len(trades)*100, 1) if trades else 0,
        "total_pnl":    round(total_pnl, 2),
        "recent_trades":trades[-20:][::-1],   # last 20, newest first
        "timestamp":    datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(_dashboard_data())

@app.route("/api/adjust_sl", methods=["POST"])
def api_adjust_sl():
    data   = request.json or {}
    symbol = data.get("symbol", "")
    new_sl = float(data.get("new_sl", 0))
    if not _bot_ref:
        return jsonify({"ok": False, "msg": "Bot not running"})
    if symbol not in _bot_ref.positions:
        return jsonify({"ok": False, "msg": f"{symbol} not found"})
    pos       = _bot_ref.positions[symbol]
    old_sl    = pos.get("sl", 0)
    direction = pos.get("direction", "BUY")
    cur_price = pos.get("last_price", pos.get("entry", 0))

    # Validate SL makes sense
    if direction == "BUY" and new_sl >= cur_price:
        return jsonify({"ok": False, "msg": f"❌ BUY SL must be below current price ₹{cur_price}"})
    if direction == "SELL" and new_sl <= cur_price:
        return jsonify({"ok": False, "msg": f"❌ SELL SL must be above current price ₹{cur_price}"})
    if new_sl <= 0:
        return jsonify({"ok": False, "msg": "❌ SL must be greater than 0"})

    pos["sl"]         = new_sl
    pos["current_sl"] = new_sl
    pos["sl_manual"]  = True   # flag so trailing SL doesn't override immediately
    log.info(f"Manual SL [{symbol}]: {old_sl} → {new_sl}")
    return jsonify({"ok": True, "msg": f"✅ SL updated: {old_sl} → {new_sl}"})

@app.route("/api/ltp")
def api_ltp():
    """Returns live LTP for all open positions."""
    if not _bot_ref or not _bot_ref.client:
        return jsonify({})
    prices = {}
    for sym, pos in _bot_ref.positions.items():
        inst = next((i for i in _bot_ref.instruments if i["symbol"] == sym), None)
        if inst:
            try:
                ltp = _bot_ref.client.get_ltp(
                    inst["exchange"], inst["symbol"], inst["token"]
                )
                if ltp:
                    prices[sym] = ltp
            except Exception:
                pass
    return jsonify(prices)

@app.route("/api/control", methods=["POST"])
def api_control():
    """Control endpoint called by dashboard buttons."""
    action = request.json.get("action", "")
    if not _bot_ref:
        return jsonify({"ok": False, "msg": "Bot not running"})

    if action == "pause":
        _bot_ref.risk.bot_paused = True
        log.info("Bot PAUSED from dashboard")
        return jsonify({"ok": True, "msg": "Bot paused"})

    if action == "resume":
        _bot_ref.risk.bot_paused = False
        log.info("Bot RESUMED from dashboard")
        return jsonify({"ok": True, "msg": "Bot resumed"})

    if action == "stop":
        _bot_ref.running = False
        log.info("Bot STOPPED from dashboard")
        return jsonify({"ok": True, "msg": "Bot stopping..."})

    if action == "emergency_exit":
        # Close all open positions immediately
        for symbol in list(_bot_ref.positions.keys()):
            pos = _bot_ref.positions.get(symbol)
            if pos:
                # Use last known close price instead of 0
                last_price = pos.get("last_price", pos.get("entry", 0))
                _bot_ref._close_position(symbol, last_price, "EMERGENCY_EXIT")
        log.warning("EMERGENCY EXIT triggered from dashboard")
        return jsonify({"ok": True, "msg": "All positions closed"})

    return jsonify({"ok": False, "msg": f"Unknown action: {action}"})


@io.on("connect")
def on_connect(auth=None):
    try:
        emit("update", _dashboard_data())
    except Exception as e:
        log.error(f"Dashboard connect error: {e}")


@io.on("request_update")
def on_request_update():
    emit("update", _dashboard_data())


def run_dashboard(bot_ref=None, port=None):
    set_bot_ref(bot_ref)
    port = port or Config.DASHBOARD_PORT
    log.info(f"Dashboard starting on port {port}")
    io.run(app, host="0.0.0.0", port=port, debug=False)
