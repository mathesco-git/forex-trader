"""
Configuration for the Forex Trading Bot.
Central place for all tunable parameters.
"""
import os
from datetime import time

# =============================================================================
# TRADING PAIRS
# =============================================================================
PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF"]

PIP_VALUES = {
    "EUR/USD": 0.0001,
    "GBP/USD": 0.0001,
    "USD/JPY": 0.01,
    "AUD/USD": 0.0001,
    "USD/CHF": 0.0001,
}

# =============================================================================
# RISK MANAGEMENT
# =============================================================================
INITIAL_CAPITAL = 10000.0
RISK_PER_TRADE = 0.01        # 1% of capital per trade
LEVERAGE = 50
MAX_OPEN_POSITIONS = 3        # Max simultaneous trades
MAX_DAILY_LOSS_PCT = 0.03    # 3% max daily drawdown — circuit breaker

# =============================================================================
# SIGNAL ENGINE
# =============================================================================
MIN_CONFLUENCE = 4            # Minimum confluence factors to enter
MIN_TREND_STRENGTH = 20       # Minimum trend strength (0-100)
ATR_SL_MULTIPLIER = 1.5       # Stop loss = entry ± (ATR × this)
ATR_TP_BASE = 1.2             # Base take profit multiplier
ATR_TP_STRONG = 2.0           # TP for 6+ confluence
ATR_TP_GOOD = 1.5             # TP for 5 confluence

# =============================================================================
# MONITORING
# =============================================================================
# How much the confluence can degrade before we flag a warning
CONFLUENCE_WARNING_DROP = 2   # If confluence drops by 2+ from entry, warn
# If confluence drops below this, force close
CONFLUENCE_FORCE_CLOSE = 2

# Trailing stop: activate when trade is X pips in profit
TRAILING_STOP_ACTIVATION_PIPS = 20
TRAILING_STOP_DISTANCE_PIPS = 15

# =============================================================================
# SCHEDULE — Forex is 24/5 (Sun 5 PM ET → Fri 5 PM ET)
# =============================================================================
MORNING_SCAN_TIME = time(8, 0)      # 8:00 AM local — user's daily scan
MONITOR_INTERVAL_MINUTES = 5        # Check every 5 min
SESSION_CLOSE_TIME = time(22, 0)    # 10:00 PM local — safety sweep before sleep

# Max hours to hold a position. If a trade hasn't hit TP/SL by then,
# the monitor auto-closes it. Prevents stale forgotten positions.
MAX_HOLD_HOURS = 16

# =============================================================================
# DATA PATHS
# =============================================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.json")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.json")
MONITORING_FILE = os.path.join(DATA_DIR, "monitoring.json")
DASHBOARD_DATA_FILE = os.path.join(BASE_DIR, "dashboard", "dashboard_data.json")

# =============================================================================
# BROKER MODE
# =============================================================================
# "mock" = paper trading with simulated fills
# "oanda" = live OANDA API (future)
BROKER_MODE = os.environ.get("BROKER_MODE", "mock")
OANDA_API_KEY = os.environ.get("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT = os.environ.get("OANDA_ENVIRONMENT", "practice")  # practice or live
