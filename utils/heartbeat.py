"""
Heartbeat system. Bot writes a timestamp to STATE_FILE every cycle.
A separate lightweight checker can call is_alive() to see if the bot
has gone silent -- the dashboard uses this to show a "Bot Offline" warning.
"""

import json
import os
from datetime import datetime, timedelta
from config import Config
from utils.logger import get_logger

log = get_logger("heartbeat")


def write_heartbeat(extra: dict = None):
    """Write current timestamp + optional state data to STATE_FILE."""
    state = {
        "last_heartbeat": datetime.now().isoformat(),
        "status": "running",
    }
    if extra:
        state.update(extra)
    try:
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        with open(Config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        log.error(f"Failed to write heartbeat: {e}")


def read_state() -> dict:
    """Read the full bot state from STATE_FILE. Returns empty dict if not found."""
    try:
        with open(Config.STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def is_alive(max_silence_seconds=120) -> bool:
    """Return True if bot wrote a heartbeat within the last max_silence_seconds."""
    state = read_state()
    last = state.get("last_heartbeat")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() < max_silence_seconds
    except Exception:
        return False


def mark_stopped():
    """Mark bot as intentionally stopped."""
    state = read_state()
    state["status"] = "stopped"
    state["stopped_at"] = datetime.now().isoformat()
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        log.error(f"Failed to mark stopped: {e}")
