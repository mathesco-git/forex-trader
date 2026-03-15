"""
Evening Closer — exits all open positions before market close.

Runs at EVENING_CLOSE_TIME (default 4:30 PM ET).
Closes every open position at current market price, regardless of P&L.
This enforces the day-trading discipline: no overnight exposure.
"""
from datetime import datetime, timezone
from app import state
from app.config import PIP_VALUES


def evening_close(data_feed, broker):
    """
    Close all open positions.

    Returns dict with:
      - close_time: ISO timestamp
      - positions_closed: list of close results
      - total_pnl_pips: float
      - total_pnl_usd: float
      - day_summary: overall day stats
    """
    close_time = datetime.now(timezone.utc).isoformat()
    positions_data = state.load_positions()
    positions = positions_data.get("positions", [])

    if not positions:
        event = {
            "time": close_time,
            "type": "EVENING_CLOSE",
            "message": "No positions to close",
        }
        state.save_monitoring_event(event)
        state.build_dashboard_data()
        return {
            "close_time": close_time,
            "positions_closed": [],
            "total_pnl_pips": 0,
            "total_pnl_usd": 0,
            "day_summary": _build_day_summary(close_time),
        }

    results = []
    total_pnl_pips = 0
    total_pnl_usd = 0

    for pos in positions:
        pair = pos["pair"]
        order_id = pos["order_id"]

        # Get current market price
        price_data = data_feed.get_current_price(pair)
        exit_price = price_data["mid"]

        # Close via broker
        close_result = broker.close_position(order_id, exit_price, "EVENING_CLOSE")

        if close_result and close_result.get("status") == "CLOSED":
            pnl_pips = close_result["pnl_pips"]
            pnl_usd = close_result["pnl_usd"]
            total_pnl_pips += pnl_pips
            total_pnl_usd += pnl_usd

            # Save to trade history
            trade_record = {
                **pos,
                "exit_price": exit_price,
                "pnl_pips": pnl_pips,
                "pnl_usd": pnl_usd,
                "close_reason": "EVENING_CLOSE",
                "closed_at": close_time,
            }
            state.save_trade(trade_record)
            state.remove_position(order_id)

            results.append({
                "pair": pair,
                "order_id": order_id,
                "direction": pos["direction"],
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "pnl_pips": pnl_pips,
                "pnl_usd": pnl_usd,
            })

            event = {
                "time": close_time,
                "type": "EVENING_CLOSE",
                "pair": pair,
                "order_id": order_id,
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "pnl_pips": pnl_pips,
                "pnl_usd": pnl_usd,
            }
            state.save_monitoring_event(event)
        else:
            results.append({
                "pair": pair,
                "order_id": order_id,
                "error": close_result.get("message", "Unknown error") if close_result else "No result",
            })

    state.build_dashboard_data()

    return {
        "close_time": close_time,
        "positions_closed": results,
        "total_pnl_pips": round(total_pnl_pips, 1),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "day_summary": _build_day_summary(close_time),
    }


def _build_day_summary(close_time):
    """Build a summary of today's trading activity."""
    trades = state.load_trades()
    all_trades = trades.get("trades", [])

    # Filter to today's trades (closed today)
    today_str = close_time[:10]
    today_trades = [t for t in all_trades if t.get("closed_at", "")[:10] == today_str]

    if not today_trades:
        return {
            "date": today_str,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl_pips": 0,
            "total_pnl_usd": 0,
            "best_trade": None,
            "worst_trade": None,
        }

    wins = [t for t in today_trades if t.get("pnl_usd", 0) > 0]
    losses = [t for t in today_trades if t.get("pnl_usd", 0) <= 0]
    total_pips = sum(t.get("pnl_pips", 0) for t in today_trades)
    total_usd = sum(t.get("pnl_usd", 0) for t in today_trades)

    best = max(today_trades, key=lambda t: t.get("pnl_usd", 0))
    worst = min(today_trades, key=lambda t: t.get("pnl_usd", 0))

    return {
        "date": today_str,
        "trades": len(today_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(today_trades) * 100, 1),
        "total_pnl_pips": round(total_pips, 1),
        "total_pnl_usd": round(total_usd, 2),
        "best_trade": {"pair": best["pair"], "pnl_usd": best.get("pnl_usd", 0)},
        "worst_trade": {"pair": worst["pair"], "pnl_usd": worst.get("pnl_usd", 0)},
    }
