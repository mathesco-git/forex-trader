"""
Morning Scanner — runs at market open to identify high-probability trades.

Logic:
  1. Pull latest historical data for all configured pairs
  2. Run the confluence engine on each pair
  3. Rank signals by confluence count and trend strength
  4. Select top candidates (respecting max open positions)
  5. Open positions via the broker (mock or real)
  6. Persist state
"""
from datetime import datetime, timezone
from app import engine, state
from app.config import (
    PAIRS, PIP_VALUES, MAX_OPEN_POSITIONS,
    INITIAL_CAPITAL, RISK_PER_TRADE, LEVERAGE,
    MIN_CONFLUENCE, MAX_DAILY_LOSS_PCT,
)


def morning_scan(data_feed, broker):
    """
    Scan all pairs, rank signals, open the best trades.

    Returns dict with:
      - scan_time: ISO timestamp
      - all_signals: full analysis for every pair
      - selected: list of pairs selected for trading
      - positions_opened: list of order confirmations
      - skipped_reason: why pairs were skipped
    """
    scan_time = datetime.now(timezone.utc).isoformat()
    all_signals = []
    tradeable = []

    # Circuit breaker check — block new trades if daily loss limit hit
    is_tripped, daily_pnl, threshold = state.check_circuit_breaker()
    if is_tripped:
        event = {
            "time": scan_time,
            "type": "CIRCUIT_BREAKER",
            "message": f"Daily loss limit hit: ${daily_pnl:.2f} (threshold: ${threshold:.2f}). No new trades.",
        }
        state.save_monitoring_event(event)
        state.build_dashboard_data()
        return {
            "scan_time": scan_time,
            "pairs_analyzed": 0,
            "signals_found": 0,
            "positions_opened": 0,
            "slots_available": 0,
            "effective_capital": 0,
            "all_signals": [],
            "selected": [],
            "skipped": [],
            "orders": [],
            "circuit_breaker": True,
            "daily_pnl": daily_pnl,
            "daily_loss_threshold": threshold,
        }

    # Analyze all pairs
    for pair in PAIRS:
        hist = data_feed.get_historical(pair, bars=40)
        pip_value = PIP_VALUES.get(pair, 0.0001)

        analysis = engine.analyze(
            pair,
            hist["closes"],
            hist["highs"],
            hist["lows"],
            pip_value=pip_value,
        )

        # Add current price info
        price = data_feed.get_current_price(pair)
        analysis["current_price"] = price
        all_signals.append(analysis)

        if analysis["signal"] != "NO TRADE" and analysis["trade"]:
            tradeable.append(analysis)

    # Rank by confluence count (desc), then trend strength (desc)
    tradeable.sort(key=lambda x: (x["confluence_count"], x["trend_strength"]), reverse=True)

    # Check how many positions we can still open
    existing = state.load_positions()
    open_count = len(existing.get("positions", []))
    slots_available = MAX_OPEN_POSITIONS - open_count

    selected = tradeable[:slots_available]
    skipped = tradeable[slots_available:]

    # Calculate position size
    capital = INITIAL_CAPITAL
    # Adjust capital for existing P&L
    trades_hist = state.load_trades()
    realized_pnl = sum(t.get("pnl_usd", 0) for t in trades_hist.get("trades", []))
    effective_capital = capital + realized_pnl

    positions_opened = []

    for sig in selected:
        pair = sig["pair"]
        trade = sig["trade"]
        pip = PIP_VALUES.get(pair, 0.0001)

        # Position sizing: risk-based
        risk_amount = effective_capital * RISK_PER_TRADE
        sl_distance = abs(trade["entry"] - trade["stop_loss"])
        if sl_distance == 0:
            continue

        # Units = risk / (SL distance)
        # For standard forex: units = risk_amount / sl_distance
        units = int(risk_amount / sl_distance)
        units = min(units, int(effective_capital * LEVERAGE))  # Leverage cap

        # Open via broker
        result = broker.open_position(
            pair=pair,
            direction=sig["direction"],
            entry_price=trade["entry"],
            stop_loss=trade["stop_loss"],
            take_profit=trade["tp1"],
            units=units,
            confluence_count=sig["confluence_count"],
            signal_strength=sig["signal"].split()[0],  # MODERATE/GOOD/STRONG
        )

        # Get the order details from broker
        order = broker.get_position(result["order_id"])

        # Persist position
        position_record = {
            **order,
            "entry_confluence": sig["confluence_count"],
            "entry_confluence_detail": sig["confluence_detail"],
            "entry_trend": sig["trend"],
            "entry_trend_strength": sig["trend_strength"],
            "entry_indicators": sig.get("indicators", {}),
            "monitoring_history": [],
            "trailing_stop_active": False,
            "trailing_stop_price": None,
        }
        state.add_position(position_record)
        positions_opened.append(result)

    # Save all signals for dashboard
    signal_records = []
    for sig in all_signals:
        signal_records.append({
            "pair": sig["pair"],
            "signal": sig["signal"],
            "direction": sig.get("direction"),
            "confluence_count": sig.get("confluence_count", 0),
            "trend": sig.get("trend", "UNKNOWN"),
            "trend_strength": sig.get("trend_strength", 0),
            "trade": sig.get("trade"),
            "reason": sig.get("reason", ""),
            "details": sig.get("details", []),
            "current_price": sig.get("current_price"),
        })

    state.save_signals(signal_records, scan_time)

    result = {
        "scan_time": scan_time,
        "pairs_analyzed": len(all_signals),
        "signals_found": len(tradeable),
        "positions_opened": len(positions_opened),
        "slots_available": slots_available,
        "effective_capital": round(effective_capital, 2),
        "all_signals": signal_records,
        "selected": [s["pair"] for s in selected],
        "skipped": [{"pair": s["pair"], "reason": "No available slots"} for s in skipped],
        "orders": positions_opened,
    }

    # Update dashboard
    state.build_dashboard_data()

    return result
