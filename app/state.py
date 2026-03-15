"""
State Manager — persists trading state to JSON files.

All bot state (open positions, signals, monitoring logs, trade history)
is stored in JSON files under data/. This makes it easy to:
  - Commit state to git (GitHub Actions can push after each run)
  - Read from the dashboard (static HTML reads the JSON)
  - Debug and audit trades
"""
import json
import os
from datetime import datetime, timezone
from app.config import DATA_DIR, POSITIONS_FILE, TRADES_FILE, SIGNALS_FILE, MONITORING_FILE


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def _write_json(path, data):
    _ensure_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── Signals (morning scan output) ──────────────────────────────────────

def save_signals(signals, scan_time=None):
    """Save morning scan signals. Overwrites previous day's scan."""
    _write_json(SIGNALS_FILE, {
        "scan_time": scan_time or _now_iso(),
        "signals": signals,
    })


def load_signals():
    return _read_json(SIGNALS_FILE, {"scan_time": None, "signals": []})


# ── Open Positions ─────────────────────────────────────────────────────

def save_positions(positions):
    """Save current open positions."""
    _write_json(POSITIONS_FILE, {
        "updated_at": _now_iso(),
        "positions": positions,
    })


def load_positions():
    return _read_json(POSITIONS_FILE, {"updated_at": None, "positions": []})


def add_position(position):
    """Add a new open position."""
    data = load_positions()
    data["positions"].append(position)
    save_positions(data["positions"])


def remove_position(order_id):
    """Remove a position (when closed)."""
    data = load_positions()
    data["positions"] = [p for p in data["positions"] if p["order_id"] != order_id]
    save_positions(data["positions"])


def update_position(order_id, updates):
    """Update fields on an open position."""
    data = load_positions()
    for p in data["positions"]:
        if p["order_id"] == order_id:
            p.update(updates)
            break
    save_positions(data["positions"])


# ── Trade History (closed trades) ──────────────────────────────────────

def save_trade(trade_record):
    """Append a closed trade to history."""
    data = _read_json(TRADES_FILE, {"trades": []})
    data["trades"].append(trade_record)
    _write_json(TRADES_FILE, data)


def load_trades():
    return _read_json(TRADES_FILE, {"trades": []})


# ── Monitoring Log ─────────────────────────────────────────────────────

def save_monitoring_event(event):
    """Append a monitoring check to the log."""
    data = _read_json(MONITORING_FILE, {"events": []})
    data["events"].append(event)
    # Keep last 200 events
    data["events"] = data["events"][-200:]
    _write_json(MONITORING_FILE, data)


def load_monitoring():
    return _read_json(MONITORING_FILE, {"events": []})


# ── Dashboard Aggregate ────────────────────────────────────────────────

def build_dashboard_data():
    """
    Build a single JSON blob for the dashboard to consume.
    Merges signals, positions, trades, and monitoring into one file.
    """
    signals = load_signals()
    positions = load_positions()
    trades = load_trades()
    monitoring = load_monitoring()

    # Calculate summary stats
    all_trades = trades.get("trades", [])
    total_pnl = sum(t.get("pnl_usd", 0) for t in all_trades)
    wins = sum(1 for t in all_trades if t.get("pnl_usd", 0) > 0)
    losses = sum(1 for t in all_trades if t.get("pnl_usd", 0) <= 0)
    win_rate = (wins / len(all_trades) * 100) if all_trades else 0

    dashboard = {
        "generated_at": _now_iso(),
        "summary": {
            "total_trades": len(all_trades),
            "open_positions": len(positions.get("positions", [])),
            "total_pnl_usd": round(total_pnl, 2),
            "win_rate": round(win_rate, 1),
            "wins": wins,
            "losses": losses,
        },
        "signals": signals,
        "positions": positions,
        "trades": trades,
        "monitoring": {
            "events": monitoring.get("events", [])[-50:],  # Last 50 for dashboard
        },
    }

    from app.config import DASHBOARD_DATA_FILE
    dash_dir = os.path.dirname(DASHBOARD_DATA_FILE)
    os.makedirs(dash_dir, exist_ok=True)
    _write_json(DASHBOARD_DATA_FILE, dashboard)
    return dashboard
