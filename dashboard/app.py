import os
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from config import Config
from utils.heartbeat import read_state, is_alive
from utils.logger import get_logger

log = get_logger("dashboard")

app = Flask(__name__)
app.secret_key = Config.DASHBOARD_SECRET_KEY
io  = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

_bot_ref = None

def set_bot_ref(bot):
    global _bot_ref
    _bot_ref = bot

def _load_trades():
    try:
        if os.path.exists(Config.TRADE_LOG_PATH):
            df = pd.read_csv(Config.TRADE_LOG_PATH)
            if "exit_time" in df.columns:
                df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
                today = pd.Timestamp.now().date()
                df    = df[df["exit_time"].dt.date == today]
            for col in df.select_dtypes(include=["datetime64[ns]","datetimetz"]).columns:
                df[col] = df[col].astype(str)
            return df.to_dict("records")
    except:
        pass
    return []

def _dashboard_data():
    state  = read_state()
    trades = _load_trades()
    wins   = [t for t in trades if float(t.get("pnl_rupees", 0)) > 0]
    total_pnl = sum(float(t.get("pnl_rupees", 0)) for t in trades)

    positions = {}
    if _bot_ref:
        for k, v in _bot_ref.positions.items():
            if not isinstance(v, dict) or not v.get("entry"):
                continue
            positions[k] = {
                "symbol":      v.get("symbol", k),
                "direction":   v.get("direction", "BUY"),
                "nifty_signal": v.get("nifty_signal", ""),
                "entry":       v.get("entry", 0),
                "sl":          v.get("sl", 0),
                "current_sl":  v.get("current_sl", v.get("sl", 0)),
                "qty":         v.get("qty", 0),
                "entry_time":  str(v.get("entry_time", "")),
                "score":       v.get("score", 0),
                "pattern":     v.get("pattern", ""),
                "high":        v.get("high", v.get("entry", 0)),
                "low":         v.get("low", v.get("entry", 0)),
                "last_price":  v.get("last_price", v.get("entry", 0)),
                "token":       v.get("token", ""),
                "exchange":    v.get("exchange", "NFO"),
            }

    return {
        "alive":        is_alive(),
        "status":       state.get("status", "unknown"),
        "mode":         state.get("mode", Config.TRADING_MODE),
        "last_beat":    state.get("last_heartbeat", "—"),
        "daily_pnl":    state.get("daily_pnl", 0),
        "trades_today": state.get("trades_today", 0),
        "market_dir":   state.get("market_dir", "NEUTRAL"),
        "instruments":  state.get("instruments", []),
        "positions":    positions,
        "total_trades": len(trades),
        "wins":         len(wins),
        "losses":       len(trades) - len(wins),
        "win_rate":     round(len(wins)/len(trades)*100, 1) if trades else 0,
        "total_pnl":    round(total_pnl, 2),
        "recent_trades": trades[-20:][::-1],
        "timestamp":    datetime.now().strftime("%H:%M:%S"),
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    return jsonify(_dashboard_data())

@app.route("/api/ltp")
def api_ltp():
    """
    Returns live prices from bot memory — updated by WebSocket ticks.
    No Angel One API calls made here. Zero rate limit impact.
    """
    if not _bot_ref:
        return jsonify({})
    prices = {}
    for sym, pos in _bot_ref.positions.items():
        if isinstance(pos, dict) and pos.get("last_price"):
            prices[sym] = pos["last_price"]
    return jsonify(prices)

@app.route("/api/adjust_sl", methods=["POST"])
def api_adjust_sl():
    data   = request.json or {}
    symbol = data.get("symbol", "")
    new_sl = float(data.get("new_sl", 0))
    if not _bot_ref:
        return jsonify({"ok": False, "msg": "Bot not running"})
    if not hasattr(_bot_ref, "adjust_sl"):
        return jsonify({"ok": False, "msg": "adjust_sl not supported"})
    ok, msg = _bot_ref.adjust_sl(symbol, new_sl)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/api/control", methods=["POST"])
def api_control():
    action = (request.json or {}).get("action", "")
    if not _bot_ref:
        return jsonify({"ok": False, "msg": "Bot not running"})
    if action == "pause":
        _bot_ref.risk.bot_paused = True
        return jsonify({"ok": True, "msg": "Bot paused"})
    if action == "resume":
        _bot_ref.risk.bot_paused = False
        return jsonify({"ok": True, "msg": "Bot resumed"})
    if action == "stop":
        _bot_ref.running = False
        return jsonify({"ok": True, "msg": "Stopping..."})
    if action == "emergency_exit":
        for sym in list(_bot_ref.positions.keys()):
            pos = _bot_ref.positions.get(sym)
            if pos:
                last = pos.get("last_price", pos.get("entry", 0))
                _bot_ref._close_position(sym, last, "EMERGENCY_EXIT")
        log.warning("EMERGENCY EXIT triggered")
        return jsonify({"ok": True, "msg": "All positions closed"})
    return jsonify({"ok": False, "msg": f"Unknown action: {action}"})

@io.on("connect")
def on_connect(auth=None):
    try:
        emit("update", _dashboard_data())
    except Exception as e:
        log.error(f"Connect error: {e}")

@io.on("request_update")
def on_request_update():
    try:
        emit("update", _dashboard_data())
    except Exception as e:
        log.error(f"Update error: {e}")

def run_dashboard(bot_ref=None, port=None):
    set_bot_ref(bot_ref)
    port = port or Config.DASHBOARD_PORT
    log.info(f"Dashboard on port {port}")
    io.run(app, host="0.0.0.0", port=port, debug=False)
