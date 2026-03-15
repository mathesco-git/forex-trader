#!/usr/bin/env python3
"""
Forex Trading Bot — Unified CLI Entry Point.

Usage:
  python main.py scan          Run morning scan (select trades)
  python main.py monitor       Run intraday monitoring check
  python main.py close         Run evening close (exit all positions)
  python main.py simulate      Simulate a full trading day (for testing)
  python main.py status        Show current positions and P&L
  python main.py dashboard     Generate dashboard data file

Environment variables:
  BROKER_MODE=mock|oanda       Select broker (default: mock)
  MOCK_SEED=42                 Seed for reproducible mock simulations
"""
import sys
import json
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import BROKER_MODE, DATA_DIR
from app.data_feed import MockDataFeed, OandaDataFeed
from app.broker import MockBroker, OandaBroker
from app import state


def get_feed_and_broker():
    """Create data feed and broker based on config."""
    seed = os.environ.get("MOCK_SEED")
    seed = int(seed) if seed else None

    if BROKER_MODE == "oanda":
        from app.config import OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_ENVIRONMENT
        feed = OandaDataFeed(OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_ENVIRONMENT)
        broker = OandaBroker(OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_ENVIRONMENT)
    else:
        feed = MockDataFeed(seed=seed)
        broker = MockBroker()

    return feed, broker


def cmd_scan():
    """Run the morning scanner."""
    from app.scanner import morning_scan
    feed, broker = get_feed_and_broker()
    result = morning_scan(feed, broker)

    print("=" * 60)
    print(f"  MORNING SCAN — {result['scan_time'][:19]}")
    print("=" * 60)
    print(f"  Pairs analyzed:     {result['pairs_analyzed']}")
    print(f"  Signals found:      {result['signals_found']}")
    print(f"  Positions opened:   {result['positions_opened']}")
    print(f"  Slots available:    {result['slots_available']}")
    print(f"  Effective capital:  ${result['effective_capital']:,.2f}")
    print()

    for sig in result["all_signals"]:
        icon = "✅" if sig["signal"] != "NO TRADE" else "⬜"
        selected = " ← SELECTED" if sig["pair"] in result["selected"] else ""
        print(f"  {icon} {sig['pair']:8s}  {sig['signal']:18s}  "
              f"Confluence: {sig['confluence_count']}/8  "
              f"Trend: {sig['trend']:12s} ({sig['trend_strength']:.0f}/100)"
              f"{selected}")

    if result["orders"]:
        print()
        print("  Orders placed:")
        for order in result["orders"]:
            print(f"    {order['order_id']}: {order['message']}")

    return result


def cmd_monitor():
    """Run intraday monitoring."""
    from app.monitor import monitor_positions
    feed, broker = get_feed_and_broker()

    # Reload broker state from persisted positions
    _reload_broker_positions(broker)

    result = monitor_positions(feed, broker)

    print("=" * 60)
    print(f"  MONITOR CHECK — {result['check_time'][:19]}")
    print("=" * 60)
    print(f"  Positions checked:  {result['positions_checked']}")
    print(f"  Actions taken:      {len(result['actions'])}")
    print()

    for action in result["actions"]:
        if action["type"] == "WARNING":
            print(f"  ⚠️  {action['pair']} — {action['reason']}")
        elif action["type"] == "FORCE_CLOSE":
            print(f"  🔴 {action['pair']} — FORCE CLOSED: {action['reason']} "
                  f"({action['pnl_pips']:+.1f} pips, ${action['pnl_usd']:+.2f})")
        elif action["type"] in ("STOP_LOSS", "TAKE_PROFIT"):
            print(f"  {'🔴' if action['type'] == 'STOP_LOSS' else '🟢'} "
                  f"{action['pair']} — {action['type']} hit "
                  f"({action['pnl_pips']:+.1f} pips, ${action['pnl_usd']:+.2f})")
        elif action["type"] == "TRAILING_STOP_UPDATE":
            print(f"  📈 {action['pair']} — Trailing stop → {action['new_stop']} "
                  f"(+{action['pnl_pips']:.1f} pips)")

    return result


def cmd_close():
    """Run evening close."""
    from app.closer import evening_close
    feed, broker = get_feed_and_broker()

    _reload_broker_positions(broker)

    result = evening_close(feed, broker)

    print("=" * 60)
    print(f"  EVENING CLOSE — {result['close_time'][:19]}")
    print("=" * 60)

    for pos in result["positions_closed"]:
        if "error" in pos:
            print(f"  ❌ {pos['pair']} — Error: {pos['error']}")
        else:
            icon = "🟢" if pos["pnl_usd"] > 0 else "🔴"
            print(f"  {icon} {pos['pair']:8s}  {pos['direction']:5s}  "
                  f"Entry: {pos['entry_price']}  Exit: {pos['exit_price']}  "
                  f"{pos['pnl_pips']:+.1f} pips  ${pos['pnl_usd']:+.2f}")

    print()
    print(f"  Day total: {result['total_pnl_pips']:+.1f} pips  ${result['total_pnl_usd']:+.2f}")

    summary = result.get("day_summary", {})
    if summary and summary.get("trades", 0) > 0:
        print()
        print(f"  Day Summary:")
        print(f"    Trades: {summary['trades']}  "
              f"W/L: {summary['wins']}/{summary['losses']}  "
              f"Win rate: {summary['win_rate']}%")

    return result


def cmd_status():
    """Show current bot status."""
    positions = state.load_positions()
    trades = state.load_trades()
    signals = state.load_signals()

    open_pos = positions.get("positions", [])
    all_trades = trades.get("trades", [])
    total_pnl = sum(t.get("pnl_usd", 0) for t in all_trades)

    print("=" * 60)
    print("  BOT STATUS")
    print("=" * 60)
    print(f"  Open positions:     {len(open_pos)}")
    print(f"  Completed trades:   {len(all_trades)}")
    print(f"  Total realized P&L: ${total_pnl:+.2f}")
    print()

    if open_pos:
        print("  Open Positions:")
        for p in open_pos:
            print(f"    {p['order_id']}: {p['direction']} {p['pair']} "
                  f"@ {p['entry_price']}  SL: {p['stop_loss']}  TP: {p['take_profit']}  "
                  f"Confluence: {p.get('current_confluence', p.get('entry_confluence', '?'))}/8  "
                  f"P&L: {p.get('current_pnl_pips', '?')} pips")
        print()

    last_signals = signals.get("signals", [])
    if last_signals:
        print(f"  Last scan: {signals.get('scan_time', 'N/A')[:19]}")
        for sig in last_signals:
            if sig["signal"] != "NO TRADE":
                print(f"    {sig['pair']:8s}  {sig['signal']:18s}  Confluence: {sig['confluence_count']}/8")


def cmd_simulate():
    """
    Simulate a full trading day: morning scan → multiple monitoring checks → evening close.
    Uses deterministic seed for reproducibility.
    """
    import random

    seed = int(os.environ.get("MOCK_SEED", "42"))
    os.environ["MOCK_SEED"] = str(seed)

    # Clean state for fresh simulation
    os.makedirs(DATA_DIR, exist_ok=True)
    empty_defaults = {
        "positions.json": '{"updated_at": null, "positions": []}',
        "trades.json": '{"trades": []}',
        "signals.json": '{"scan_time": null, "signals": []}',
        "monitoring.json": '{"events": []}',
    }
    for f, default in empty_defaults.items():
        path = os.path.join(DATA_DIR, f)
        try:
            if os.path.exists(path):
                os.remove(path)
        except PermissionError:
            with open(path, "w") as fh:
                fh.write(default)

    print("=" * 60)
    print(f"  FULL DAY SIMULATION (seed={seed})")
    print("=" * 60)
    print()

    # Phase 1: Morning Scan
    print("━" * 60)
    print("  PHASE 1: Morning Scan (8:00 AM ET)")
    print("━" * 60)
    from app.scanner import morning_scan
    feed = MockDataFeed(seed=seed)
    broker = MockBroker()
    scan_result = morning_scan(feed, broker)

    for sig in scan_result["all_signals"]:
        icon = "✅" if sig["signal"] != "NO TRADE" else "⬜"
        selected = " ← OPENED" if sig["pair"] in scan_result["selected"] else ""
        print(f"  {icon} {sig['pair']:8s}  {sig['signal']:18s}  "
              f"Confluence: {sig['confluence_count']}/8{selected}")

    if scan_result["orders"]:
        print()
        for order in scan_result["orders"]:
            print(f"  📝 {order['message']}")

    # Phase 2: Monitoring (simulate 8 checks, every 30 min from 9:00-12:30)
    print()
    print("━" * 60)
    print("  PHASE 2: Intraday Monitoring (9:00 AM - 4:00 PM ET)")
    print("━" * 60)

    from app.monitor import monitor_positions

    # Run monitoring 14 times (every 30 min, 7 hours)
    for check_num in range(1, 15):
        # Slightly vary the seed each check to simulate time passing
        feed_check = MockDataFeed(seed=seed + check_num * 100)
        broker_check = MockBroker()
        _reload_broker_positions(broker_check)

        mon_result = monitor_positions(feed_check, broker_check)

        time_label = f"Check #{check_num:2d}"
        open_count = len(state.load_positions().get("positions", []))

        if mon_result["actions"]:
            for action in mon_result["actions"]:
                if action["type"] == "WARNING":
                    print(f"  {time_label}: ⚠️  {action['pair']} — {action['reason']}")
                elif action["type"] == "FORCE_CLOSE":
                    print(f"  {time_label}: 🔴 {action['pair']} FORCE CLOSED "
                          f"({action['pnl_pips']:+.1f} pips, ${action['pnl_usd']:+.2f})")
                elif action["type"] in ("STOP_LOSS", "TAKE_PROFIT"):
                    icon = "🔴" if action["type"] == "STOP_LOSS" else "🟢"
                    print(f"  {time_label}: {icon} {action['pair']} {action['type']} "
                          f"({action['pnl_pips']:+.1f} pips, ${action['pnl_usd']:+.2f})")
                elif action["type"] == "TRAILING_STOP_UPDATE":
                    print(f"  {time_label}: 📈 {action['pair']} trail → {action['new_stop']}")
        else:
            if open_count > 0:
                # Show current P&L snapshot
                positions = state.load_positions().get("positions", [])
                pnl_str = ", ".join(
                    f"{p['pair']}: {p.get('current_pnl_pips', 0):+.1f} pips"
                    for p in positions
                )
                print(f"  {time_label}: ✓ {open_count} position(s) OK — {pnl_str}")
            else:
                print(f"  {time_label}: ✓ No open positions")

    # Phase 3: Evening Close
    print()
    print("━" * 60)
    print("  PHASE 3: Evening Close (4:30 PM ET)")
    print("━" * 60)

    from app.closer import evening_close
    feed_close = MockDataFeed(seed=seed + 9999)
    broker_close = MockBroker()
    _reload_broker_positions(broker_close)

    close_result = evening_close(feed_close, broker_close)

    for pos in close_result["positions_closed"]:
        if "error" in pos:
            print(f"  ❌ {pos['pair']} — Error: {pos['error']}")
        else:
            icon = "🟢" if pos["pnl_usd"] > 0 else "🔴"
            print(f"  {icon} {pos['pair']:8s}  {pos['direction']:5s}  "
                  f"Entry: {pos['entry_price']}  Exit: {pos['exit_price']}  "
                  f"{pos['pnl_pips']:+.1f} pips  ${pos['pnl_usd']:+.2f}")

    # Final summary
    print()
    print("━" * 60)
    print("  DAY SUMMARY")
    print("━" * 60)
    all_trades = state.load_trades().get("trades", [])
    total_pnl = sum(t.get("pnl_usd", 0) for t in all_trades)
    total_pips = sum(t.get("pnl_pips", 0) for t in all_trades)
    wins = sum(1 for t in all_trades if t.get("pnl_usd", 0) > 0)
    losses = sum(1 for t in all_trades if t.get("pnl_usd", 0) <= 0)

    print(f"  Total trades:       {len(all_trades)}")
    print(f"  Wins / Losses:      {wins} / {losses}")
    print(f"  Win rate:           {wins/len(all_trades)*100:.1f}%" if all_trades else "  Win rate:           N/A")
    print(f"  Total P&L (pips):   {total_pips:+.1f}")
    print(f"  Total P&L (USD):    ${total_pnl:+.2f}")

    # Generate dashboard data
    state.build_dashboard_data()
    print()
    print("  Dashboard data updated → dashboard/dashboard_data.json")

    return {
        "scan": scan_result,
        "close": close_result,
        "trades": all_trades,
        "total_pnl": total_pnl,
    }


def cmd_dashboard():
    """Generate dashboard data file."""
    dashboard = state.build_dashboard_data()
    print(f"Dashboard data written. Summary:")
    print(f"  Total trades:    {dashboard['summary']['total_trades']}")
    print(f"  Open positions:  {dashboard['summary']['open_positions']}")
    print(f"  Total P&L:       ${dashboard['summary']['total_pnl_usd']:+.2f}")
    print(f"  Win rate:        {dashboard['summary']['win_rate']}%")


def _reload_broker_positions(broker):
    """
    Reload open positions from state into the broker's memory.
    Needed because broker is in-memory only and doesn't persist between runs.
    """
    positions = state.load_positions()
    for pos in positions.get("positions", []):
        broker._orders[pos["order_id"]] = {
            "order_id": pos["order_id"],
            "pair": pos["pair"],
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "stop_loss": pos.get("trailing_stop_price") or pos["stop_loss"],
            "take_profit": pos["take_profit"],
            "units": pos["units"],
            "confluence_at_entry": pos.get("entry_confluence", 0),
            "signal_strength": pos.get("signal_strength", "MODERATE"),
            "status": "OPEN",
            "opened_at": pos.get("opened_at"),
            "closed_at": None,
            "exit_price": None,
            "pnl_pips": None,
            "pnl_usd": None,
            "close_reason": None,
        }


COMMANDS = {
    "scan": cmd_scan,
    "monitor": cmd_monitor,
    "close": cmd_close,
    "status": cmd_status,
    "simulate": cmd_simulate,
    "dashboard": cmd_dashboard,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("Available commands:")
        for name, func in COMMANDS.items():
            print(f"  {name:12s}  {func.__doc__.strip()}")
        sys.exit(1)

    command = sys.argv[1]
    COMMANDS[command]()


if __name__ == "__main__":
    main()
