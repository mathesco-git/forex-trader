"""
Intraday Monitor — checks open positions and validates trade signals.

Runs every 5 minutes. For each open position:
  1. Get current price
  2. Check if SL or TP was hit
  3. Check max hold duration (auto-close stale positions)
  4. Re-run confluence analysis with updated data
  5. Check for confluence degradation → warn or force close
  6. Manage trailing stops
  7. Log monitoring event
"""
from datetime import datetime, timezone, timedelta
from app import engine, state
from app.config import (
    PIP_VALUES, CONFLUENCE_WARNING_DROP, CONFLUENCE_FORCE_CLOSE,
    TRAILING_STOP_ACTIVATION_PIPS, TRAILING_STOP_DISTANCE_PIPS,
    MAX_HOLD_HOURS,
)


def monitor_positions(data_feed, broker):
    """
    Check all open positions and take action if needed.

    Returns dict with:
      - check_time: ISO timestamp
      - positions_checked: int
      - actions: list of actions taken (warnings, closes, trailing stop updates)
      - closed_positions: list of positions that were closed
    """
    check_time = datetime.now(timezone.utc).isoformat()
    positions_data = state.load_positions()
    positions = positions_data.get("positions", [])

    if not positions:
        event = {
            "time": check_time,
            "type": "NO_POSITIONS",
            "message": "No open positions to monitor",
        }
        state.save_monitoring_event(event)
        state.build_dashboard_data()
        return {
            "check_time": check_time,
            "positions_checked": 0,
            "actions": [],
            "closed_positions": [],
        }

    actions = []
    closed_positions = []

    for pos in list(positions):  # iterate copy since we may modify
        pair = pos["pair"]
        order_id = pos["order_id"]
        pip = PIP_VALUES.get(pair, 0.0001)

        # 1. Get current price
        price_data = data_feed.get_current_price(pair)
        current_price = price_data["mid"]

        # 2. Check SL/TP hit
        # Simulate high/low for this monitoring period
        spread = price_data.get("spread_pips", 2) * pip
        check_high = current_price + spread * 2
        check_low = current_price - spread * 2

        stop_result = broker.check_stops(order_id, check_high, check_low)
        if stop_result:
            # Position was closed by SL or TP
            trade_record = {
                **pos,
                "exit_price": stop_result["exit_price"],
                "pnl_pips": stop_result["pnl_pips"],
                "pnl_usd": stop_result["pnl_usd"],
                "close_reason": stop_result["reason"],
                "closed_at": check_time,
            }
            state.save_trade(trade_record)
            state.remove_position(order_id)

            action = {
                "type": stop_result["reason"],
                "pair": pair,
                "order_id": order_id,
                "pnl_pips": stop_result["pnl_pips"],
                "pnl_usd": stop_result["pnl_usd"],
                "message": stop_result["message"],
            }
            actions.append(action)
            closed_positions.append(trade_record)

            event = {
                "time": check_time,
                "type": stop_result["reason"],
                "pair": pair,
                "order_id": order_id,
                "price": current_price,
                "pnl_pips": stop_result["pnl_pips"],
                "pnl_usd": stop_result["pnl_usd"],
            }
            state.save_monitoring_event(event)
            continue

        # 3. Check max hold duration
        opened_at = pos.get("opened_at")
        if opened_at and MAX_HOLD_HOURS > 0:
            try:
                open_dt = datetime.fromisoformat(opened_at)
                now_dt = datetime.now(timezone.utc)
                hold_hours = (now_dt - open_dt).total_seconds() / 3600
                if hold_hours >= MAX_HOLD_HOURS:
                    close_result = broker.close_position(order_id, current_price, "MAX_HOLD_EXCEEDED")
                    if close_result and close_result.get("status") == "CLOSED":
                        trade_record = {
                            **pos,
                            "exit_price": current_price,
                            "pnl_pips": close_result["pnl_pips"],
                            "pnl_usd": close_result["pnl_usd"],
                            "close_reason": f"MAX_HOLD_EXCEEDED ({hold_hours:.1f}h)",
                            "closed_at": check_time,
                        }
                        state.save_trade(trade_record)
                        state.remove_position(order_id)

                        action = {
                            "type": "MAX_HOLD_CLOSE",
                            "pair": pair,
                            "order_id": order_id,
                            "hold_hours": round(hold_hours, 1),
                            "pnl_pips": close_result["pnl_pips"],
                            "pnl_usd": close_result["pnl_usd"],
                        }
                        actions.append(action)
                        closed_positions.append(trade_record)

                        event = {
                            "time": check_time,
                            "type": "MAX_HOLD_CLOSE",
                            "pair": pair,
                            "order_id": order_id,
                            "price": current_price,
                            "hold_hours": round(hold_hours, 1),
                            "pnl_pips": close_result["pnl_pips"],
                            "pnl_usd": close_result["pnl_usd"],
                        }
                        state.save_monitoring_event(event)
                        continue
            except (ValueError, TypeError):
                pass  # Invalid timestamp, skip check

        # 4. Re-run confluence analysis
        hist = data_feed.get_historical(pair, bars=40)
        analysis = engine.analyze(pair, hist["closes"], hist["highs"], hist["lows"], pip)

        current_confluence = analysis.get("confluence_count", 0)
        entry_confluence = pos.get("entry_confluence", 0)
        confluence_drop = entry_confluence - current_confluence

        # 5. Check for confluence degradation
        if current_confluence < CONFLUENCE_FORCE_CLOSE:
            # Force close — signal has completely degraded
            close_result = broker.close_position(order_id, current_price, "CONFLUENCE_DEGRADED")
            if close_result and close_result.get("status") == "CLOSED":
                trade_record = {
                    **pos,
                    "exit_price": current_price,
                    "pnl_pips": close_result["pnl_pips"],
                    "pnl_usd": close_result["pnl_usd"],
                    "close_reason": "CONFLUENCE_DEGRADED",
                    "closed_at": check_time,
                }
                state.save_trade(trade_record)
                state.remove_position(order_id)

                action = {
                    "type": "FORCE_CLOSE",
                    "pair": pair,
                    "order_id": order_id,
                    "reason": f"Confluence dropped to {current_confluence} (was {entry_confluence})",
                    "pnl_pips": close_result["pnl_pips"],
                    "pnl_usd": close_result["pnl_usd"],
                }
                actions.append(action)
                closed_positions.append(trade_record)

                event = {
                    "time": check_time,
                    "type": "FORCE_CLOSE",
                    "pair": pair,
                    "order_id": order_id,
                    "price": current_price,
                    "confluence_now": current_confluence,
                    "confluence_entry": entry_confluence,
                    "pnl_pips": close_result["pnl_pips"],
                    "pnl_usd": close_result["pnl_usd"],
                }
                state.save_monitoring_event(event)
                continue

        elif confluence_drop >= CONFLUENCE_WARNING_DROP:
            action = {
                "type": "WARNING",
                "pair": pair,
                "order_id": order_id,
                "reason": f"Confluence dropped by {confluence_drop} ({entry_confluence} → {current_confluence})",
            }
            actions.append(action)

            event = {
                "time": check_time,
                "type": "CONFLUENCE_WARNING",
                "pair": pair,
                "order_id": order_id,
                "price": current_price,
                "confluence_now": current_confluence,
                "confluence_entry": entry_confluence,
            }
            state.save_monitoring_event(event)

        # 6. Trailing stop management
        direction = pos["direction"]
        entry_price = pos["entry_price"]

        if direction == "LONG":
            pnl_pips = (current_price - entry_price) / pip
        else:
            pnl_pips = (entry_price - current_price) / pip

        if pnl_pips >= TRAILING_STOP_ACTIVATION_PIPS:
            trail_distance = TRAILING_STOP_DISTANCE_PIPS * pip

            if direction == "LONG":
                new_trail = current_price - trail_distance
                old_sl = pos.get("trailing_stop_price") or pos["stop_loss"]
                if new_trail > old_sl:
                    state.update_position(order_id, {
                        "trailing_stop_active": True,
                        "trailing_stop_price": round(new_trail, 5 if pip == 0.0001 else 3),
                        "stop_loss": round(new_trail, 5 if pip == 0.0001 else 3),
                    })
                    # Also update in broker
                    broker_pos = broker.get_position(order_id)
                    if broker_pos:
                        broker_pos["stop_loss"] = new_trail

                    action = {
                        "type": "TRAILING_STOP_UPDATE",
                        "pair": pair,
                        "order_id": order_id,
                        "new_stop": round(new_trail, 5 if pip == 0.0001 else 3),
                        "pnl_pips": round(pnl_pips, 1),
                    }
                    actions.append(action)
            else:
                new_trail = current_price + trail_distance
                old_sl = pos.get("trailing_stop_price") or pos["stop_loss"]
                if new_trail < old_sl:
                    state.update_position(order_id, {
                        "trailing_stop_active": True,
                        "trailing_stop_price": round(new_trail, 5 if pip == 0.0001 else 3),
                        "stop_loss": round(new_trail, 5 if pip == 0.0001 else 3),
                    })
                    broker_pos = broker.get_position(order_id)
                    if broker_pos:
                        broker_pos["stop_loss"] = new_trail

                    action = {
                        "type": "TRAILING_STOP_UPDATE",
                        "pair": pair,
                        "order_id": order_id,
                        "new_stop": round(new_trail, 5 if pip == 0.0001 else 3),
                        "pnl_pips": round(pnl_pips, 1),
                    }
                    actions.append(action)

        # 7. Log regular monitoring check
        monitoring_snapshot = {
            "time": check_time,
            "price": current_price,
            "confluence": current_confluence,
            "pnl_pips": round(pnl_pips, 1),
        }

        # Add to position's monitoring history
        mon_hist = pos.get("monitoring_history", [])
        mon_hist.append(monitoring_snapshot)
        # Keep last 20 snapshots per position
        mon_hist = mon_hist[-20:]
        state.update_position(order_id, {
            "monitoring_history": mon_hist,
            "last_check": check_time,
            "current_confluence": current_confluence,
            "current_pnl_pips": round(pnl_pips, 1),
        })

        event = {
            "time": check_time,
            "type": "CHECK",
            "pair": pair,
            "order_id": order_id,
            "price": current_price,
            "confluence_now": current_confluence,
            "confluence_entry": entry_confluence,
            "pnl_pips": round(pnl_pips, 1),
            "trailing_stop": pos.get("trailing_stop_active", False),
        }
        state.save_monitoring_event(event)

    state.build_dashboard_data()

    return {
        "check_time": check_time,
        "positions_checked": len(positions),
        "actions": actions,
        "closed_positions": closed_positions,
    }
