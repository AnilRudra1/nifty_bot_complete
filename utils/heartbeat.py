import json
import os
from datetime import datetime
from config import Config

def write_heartbeat(extra=None):
    state = {"last_heartbeat": datetime.now().isoformat(), "status": "running"}
    if extra:
        state.update(extra)
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        pass

def read_state():
    try:
        with open(Config.STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def is_alive(max_silence=120):
    state = read_state()
    last  = state.get("last_heartbeat")
    if not last:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(last)).total_seconds() < max_silence
    except:
        return False

def mark_stopped():
    state = read_state()
    state["status"]     = "stopped"
    state["stopped_at"] = datetime.now().isoformat()
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except:
        pass
