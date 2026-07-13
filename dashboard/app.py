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
            return pd.read_csv(Config.TRADE_LOG_PATH).to_dict("records")
    except Exception:
        pass
    return []


def _dashboard_data() -> dict:
    state  = read_state()
    trades = _load_trades()
    wins   = [t for t in trades if t.get("pnl_rupees", 0) > 0]
    total_pnl = sum(t.get("pnl_rupees", 0) for t in trades)
    positions = {}
    if _bot_ref:
        positions = {k: {**v, "entry_time": str(v.get("entry_time", ""))}
                     for k, v in _bot_ref.positions.items()}

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
                _bot_ref._close_position(symbol, 0, "EMERGENCY_EXIT")
        log.warning("EMERGENCY EXIT triggered from dashboard")
        return jsonify({"ok": True, "msg": "All positions closed"})

    return jsonify({"ok": False, "msg": f"Unknown action: {action}"})


@io.on("connect")
def on_connect():
    emit("update", _dashboard_data())


@io.on("request_update")
def on_request_update():
    emit("update", _dashboard_data())


def run_dashboard(bot_ref=None, port=None):
    set_bot_ref(bot_ref)
    port = port or Config.DASHBOARD_PORT
    log.info(f"Dashboard starting on port {port}")
    io.run(app, host="0.0.0.0", port=port, debug=False)
