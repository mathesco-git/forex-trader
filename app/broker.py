"""
Broker — handles trade execution.

MockBroker: simulates order fills without real API calls.
OandaBroker: (future) executes via OANDA v20 API.

Both implement:
  - open_position(pair, direction, entry, sl, tp, size) → order_id
  - close_position(order_id, exit_price) → fill_result
  - get_position(order_id) → position_details
"""
import uuid
from datetime import datetime


class MockBroker:
    """
    Paper trading broker. Simulates instant fills at requested prices.
    Tracks all orders in memory.
    """

    def __init__(self):
        self._orders = {}

    def open_position(self, pair, direction, entry_price, stop_loss, take_profit,
                      units, confluence_count=0, signal_strength="MODERATE"):
        """
        Simulate opening a position.
        Returns order_id and fill details.
        """
        order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow().isoformat()

        order = {
            "order_id": order_id,
            "pair": pair,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "units": units,
            "confluence_at_entry": confluence_count,
            "signal_strength": signal_strength,
            "status": "OPEN",
            "opened_at": now,
            "closed_at": None,
            "exit_price": None,
            "pnl_pips": None,
            "pnl_usd": None,
            "close_reason": None,
        }
        self._orders[order_id] = order

        return {
            "order_id": order_id,
            "status": "FILLED",
            "fill_price": entry_price,
            "timestamp": now,
            "message": f"Mock order filled: {direction} {pair} @ {entry_price}",
        }

    def close_position(self, order_id, exit_price, reason="MANUAL"):
        """
        Simulate closing a position.
        Calculates P&L based on entry/exit prices.
        """
        if order_id not in self._orders:
            return {"status": "ERROR", "message": f"Order {order_id} not found"}

        order = self._orders[order_id]
        if order["status"] != "OPEN":
            return {"status": "ERROR", "message": f"Order {order_id} is already {order['status']}"}

        from app.config import PIP_VALUES
        pip = PIP_VALUES.get(order["pair"], 0.0001)

        if order["direction"] == "LONG":
            pnl_pips = (exit_price - order["entry_price"]) / pip
        else:
            pnl_pips = (order["entry_price"] - exit_price) / pip

        # Simplified P&L: pips × $10 per standard lot pip (for 100k units)
        # Scale by actual position size
        pnl_usd = pnl_pips * pip * order["units"]

        now = datetime.utcnow().isoformat()
        order["status"] = "CLOSED"
        order["closed_at"] = now
        order["exit_price"] = exit_price
        order["pnl_pips"] = round(pnl_pips, 1)
        order["pnl_usd"] = round(pnl_usd, 2)
        order["close_reason"] = reason

        return {
            "order_id": order_id,
            "status": "CLOSED",
            "exit_price": exit_price,
            "pnl_pips": round(pnl_pips, 1),
            "pnl_usd": round(pnl_usd, 2),
            "reason": reason,
            "timestamp": now,
            "message": f"Mock close: {order['pair']} @ {exit_price} ({pnl_pips:+.1f} pips, ${pnl_usd:+.2f})",
        }

    def check_stops(self, order_id, current_high, current_low):
        """
        Check if SL or TP was hit during current bar.
        Returns None if neither hit, or close result if triggered.
        """
        if order_id not in self._orders:
            return None

        order = self._orders[order_id]
        if order["status"] != "OPEN":
            return None

        if order["direction"] == "LONG":
            if current_low <= order["stop_loss"]:
                return self.close_position(order_id, order["stop_loss"], "STOP_LOSS")
            if current_high >= order["take_profit"]:
                return self.close_position(order_id, order["take_profit"], "TAKE_PROFIT")
        else:
            if current_high >= order["stop_loss"]:
                return self.close_position(order_id, order["stop_loss"], "STOP_LOSS")
            if current_low <= order["take_profit"]:
                return self.close_position(order_id, order["take_profit"], "TAKE_PROFIT")

        return None

    def get_position(self, order_id):
        """Get current state of an order."""
        return self._orders.get(order_id)

    def get_open_positions(self):
        """Get all currently open positions."""
        return [o for o in self._orders.values() if o["status"] == "OPEN"]


class OandaBroker:
    """
    Future: OANDA v20 API broker.
    Implements the same interface as MockBroker.
    """

    def __init__(self, api_key, account_id, environment="practice"):
        self.api_key = api_key
        self.account_id = account_id
        self.environment = environment

    def open_position(self, pair, direction, entry_price, stop_loss, take_profit,
                      units, confluence_count=0, signal_strength="MODERATE"):
        raise NotImplementedError("OANDA broker not yet implemented. Use MockBroker.")

    def close_position(self, order_id, exit_price, reason="MANUAL"):
        raise NotImplementedError("OANDA broker not yet implemented. Use MockBroker.")
