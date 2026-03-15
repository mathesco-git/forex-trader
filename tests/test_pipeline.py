#!/usr/bin/env python3
"""
Integration tests for the full trading pipeline.
Tests the morning->monitor->close cycle with deterministic data.
"""
import os
import sys
import json
import unittest
import shutil
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_feed import MockDataFeed
from app.broker import MockBroker
from app import engine


class TestIndicators(unittest.TestCase):
    """Test that indicators produce valid outputs."""

    def test_sma(self):
        from app.indicators import sma
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = sma(data, 3)
        self.assertIsNone(result[0])
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[9], 9.0)

    def test_ema(self):
        from app.indicators import ema
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = ema(data, 3)
        self.assertIsNotNone(result[2])
        self.assertIsNotNone(result[9])

    def test_rsi(self):
        from app.indicators import rsi
        data = list(range(1, 30))  # Uptrend
        result = rsi(data, 14)
        self.assertIsNotNone(result[-1])
        self.assertGreater(result[-1], 50)

    def test_atr(self):
        from app.indicators import atr
        highs = [1.1 + i * 0.01 for i in range(20)]
        lows = [1.0 + i * 0.01 for i in range(20)]
        closes = [1.05 + i * 0.01 for i in range(20)]
        result = atr(highs, lows, closes, 14)
        self.assertIsNotNone(result[-1])
        self.assertGreater(result[-1], 0)


class TestEngine(unittest.TestCase):
    """Test the signal analysis engine."""

    def setUp(self):
        self.feed = MockDataFeed(seed=42)

    def test_analyze_returns_valid_structure(self):
        hist = self.feed.get_historical("EUR/USD", bars=40)
        result = engine.analyze("EUR/USD", hist["closes"], hist["highs"], hist["lows"])
        self.assertIn("pair", result)
        self.assertIn("signal", result)
        self.assertIn("confluence_count", result)
        self.assertEqual(result["pair"], "EUR/USD")

    def test_analyze_all_pairs(self):
        from app.config import PAIRS
        for pair in PAIRS:
            hist = self.feed.get_historical(pair, bars=40)
            result = engine.analyze(pair, hist["closes"], hist["highs"], hist["lows"])
            self.assertIn("signal", result)
            self.assertIsInstance(result["confluence_count"], int)
            self.assertGreaterEqual(result["confluence_count"], 0)
            self.assertLessEqual(result["confluence_count"], 8)

    def test_no_trade_on_insufficient_data(self):
        result = engine.analyze("EUR/USD", [1.1, 1.2], [1.15, 1.25], [1.05, 1.15])
        self.assertEqual(result["signal"], "NO TRADE")


class TestDataFeed(unittest.TestCase):
    """Test the mock data feed."""

    def test_historical_data_length(self):
        feed = MockDataFeed(seed=42)
        hist = feed.get_historical("EUR/USD", bars=40)
        self.assertEqual(len(hist["closes"]), 40)
        self.assertEqual(len(hist["highs"]), 40)
        self.assertEqual(len(hist["lows"]), 40)

    def test_current_price_has_spread(self):
        feed = MockDataFeed(seed=42)
        price = feed.get_current_price("EUR/USD")
        self.assertIn("bid", price)
        self.assertIn("ask", price)
        self.assertIn("mid", price)
        self.assertGreater(price["ask"], price["bid"])

    def test_deterministic_with_seed(self):
        feed1 = MockDataFeed(seed=42)
        feed2 = MockDataFeed(seed=42)
        h1 = feed1.get_historical("EUR/USD")
        h2 = feed2.get_historical("EUR/USD")
        self.assertEqual(h1["closes"], h2["closes"])

    def test_simulate_price_movement(self):
        feed = MockDataFeed(seed=42)
        points = feed.simulate_price_movement("EUR/USD", 1.1500, hours=4)
        self.assertEqual(len(points), 8)
        for p in points:
            self.assertIn("timestamp", p)
            self.assertIn("price", p)


class TestBroker(unittest.TestCase):
    """Test the mock broker."""

    def test_open_and_close_position(self):
        broker = MockBroker()
        result = broker.open_position("EUR/USD", "LONG", 1.1500, 1.1450, 1.1600, 10000)
        self.assertEqual(result["status"], "FILLED")
        order_id = result["order_id"]

        pos = broker.get_position(order_id)
        self.assertEqual(pos["status"], "OPEN")

        close = broker.close_position(order_id, 1.1550, "TEST")
        self.assertEqual(close["status"], "CLOSED")
        self.assertGreater(close["pnl_pips"], 0)

    def test_stop_loss_hit(self):
        broker = MockBroker()
        result = broker.open_position("EUR/USD", "LONG", 1.1500, 1.1450, 1.1600, 10000)
        order_id = result["order_id"]

        sl_result = broker.check_stops(order_id, 1.1510, 1.1440)
        self.assertIsNotNone(sl_result)
        self.assertEqual(sl_result["reason"], "STOP_LOSS")

    def test_take_profit_hit(self):
        broker = MockBroker()
        result = broker.open_position("EUR/USD", "LONG", 1.1500, 1.1450, 1.1600, 10000)
        order_id = result["order_id"]

        tp_result = broker.check_stops(order_id, 1.1610, 1.1490)
        self.assertIsNotNone(tp_result)
        self.assertEqual(tp_result["reason"], "TAKE_PROFIT")


def _setup_temp_state(test_dir):
    """Patch config paths to use a temp directory."""
    import app.config as cfg
    import app.state as st
    import importlib

    os.makedirs(test_dir, exist_ok=True)
    cfg.DATA_DIR = test_dir
    cfg.POSITIONS_FILE = os.path.join(test_dir, "positions.json")
    cfg.TRADES_FILE = os.path.join(test_dir, "trades.json")
    cfg.SIGNALS_FILE = os.path.join(test_dir, "signals.json")
    cfg.MONITORING_FILE = os.path.join(test_dir, "monitoring.json")
    cfg.DASHBOARD_DATA_FILE = os.path.join(test_dir, "dashboard_data.json")
    importlib.reload(st)


class TestState(unittest.TestCase):
    """Test state persistence."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="forex_test_state_")
        _setup_temp_state(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_load_signals(self):
        from app import state
        signals = [{"pair": "EUR/USD", "signal": "STRONG LONG"}]
        state.save_signals(signals)
        loaded = state.load_signals()
        self.assertEqual(len(loaded["signals"]), 1)
        self.assertEqual(loaded["signals"][0]["pair"], "EUR/USD")

    def test_add_and_remove_position(self):
        from app import state
        pos = {"order_id": "TEST-001", "pair": "EUR/USD", "direction": "LONG"}
        state.add_position(pos)
        loaded = state.load_positions()
        self.assertEqual(len(loaded["positions"]), 1)

        state.remove_position("TEST-001")
        loaded = state.load_positions()
        self.assertEqual(len(loaded["positions"]), 0)

    def test_save_trade_history(self):
        from app import state
        state.save_trade({"pair": "EUR/USD", "pnl_usd": 50.0})
        state.save_trade({"pair": "GBP/USD", "pnl_usd": -20.0})
        loaded = state.load_trades()
        self.assertEqual(len(loaded["trades"]), 2)


class TestPipeline(unittest.TestCase):
    """Integration test: full morning->monitor->close cycle."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="forex_test_pipeline_")
        _setup_temp_state(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_day_cycle(self):
        """Test the complete morning->monitor->evening cycle."""
        from app import state
        from app.scanner import morning_scan
        from app.monitor import monitor_positions
        from app.closer import evening_close

        seed = 42
        feed = MockDataFeed(seed=seed)
        broker = MockBroker()

        # 1. Morning scan
        scan_result = morning_scan(feed, broker)
        self.assertIn("scan_time", scan_result)
        self.assertEqual(scan_result["pairs_analyzed"], 5)
        self.assertGreaterEqual(scan_result["signals_found"], 0)

        # Verify state was persisted
        signals = state.load_signals()
        self.assertEqual(len(signals["signals"]), 5)

        positions_opened = scan_result["positions_opened"]

        if positions_opened > 0:
            # 2. Monitor
            positions = state.load_positions()
            self.assertGreater(len(positions["positions"]), 0)

            feed_mon = MockDataFeed(seed=seed + 100)
            broker_mon = MockBroker()
            for pos in positions["positions"]:
                broker_mon._orders[pos["order_id"]] = {
                    "order_id": pos["order_id"],
                    "pair": pos["pair"],
                    "direction": pos["direction"],
                    "entry_price": pos["entry_price"],
                    "stop_loss": pos["stop_loss"],
                    "take_profit": pos["take_profit"],
                    "units": pos["units"],
                    "status": "OPEN",
                    "opened_at": pos.get("opened_at"),
                    "closed_at": None, "exit_price": None,
                    "pnl_pips": None, "pnl_usd": None, "close_reason": None,
                }

            mon_result = monitor_positions(feed_mon, broker_mon)
            self.assertIn("check_time", mon_result)

            # 3. Evening close
            remaining = state.load_positions()
            if remaining["positions"]:
                feed_close = MockDataFeed(seed=seed + 9999)
                broker_close = MockBroker()
                for pos in remaining["positions"]:
                    broker_close._orders[pos["order_id"]] = {
                        "order_id": pos["order_id"],
                        "pair": pos["pair"],
                        "direction": pos["direction"],
                        "entry_price": pos["entry_price"],
                        "stop_loss": pos.get("trailing_stop_price") or pos["stop_loss"],
                        "take_profit": pos["take_profit"],
                        "units": pos["units"],
                        "status": "OPEN",
                        "opened_at": pos.get("opened_at"),
                        "closed_at": None, "exit_price": None,
                        "pnl_pips": None, "pnl_usd": None, "close_reason": None,
                    }

                close_result = evening_close(feed_close, broker_close)
                self.assertIn("close_time", close_result)

                # All positions should be closed
                final_positions = state.load_positions()
                self.assertEqual(len(final_positions["positions"]), 0)

        # 4. Verify dashboard data
        dashboard = state.build_dashboard_data()
        self.assertIn("summary", dashboard)
        self.assertIn("signals", dashboard)
        self.assertIn("positions", dashboard)
        self.assertIn("trades", dashboard)

    def test_no_signals_no_crash(self):
        """Test graceful handling when no positions exist."""
        from app.monitor import monitor_positions
        from app.closer import evening_close

        feed = MockDataFeed(seed=999)
        broker = MockBroker()

        # Monitor and close with no open positions
        mon = monitor_positions(feed, broker)
        self.assertEqual(mon["positions_checked"], 0)

        close = evening_close(feed, broker)
        self.assertEqual(len(close["positions_closed"]), 0)

    def test_max_positions_respected(self):
        """Test that we don't open more than MAX_OPEN_POSITIONS."""
        from app import state
        from app.config import MAX_OPEN_POSITIONS
        from app.scanner import morning_scan

        feed = MockDataFeed(seed=42)
        broker = MockBroker()

        scan = morning_scan(feed, broker)
        positions = state.load_positions()
        self.assertLessEqual(len(positions["positions"]), MAX_OPEN_POSITIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
