#!/usr/bin/env python3
"""
Integration tests for the full trading pipeline.
Tests the morning->monitor->close cycle with deterministic data.
Covers: indicators, engine, data feed, broker, state, scanner,
        monitor, closer, prognosis, circuit breaker, and full pipeline.
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

    def test_rsi_downtrend(self):
        from app.indicators import rsi
        data = list(range(30, 0, -1))  # Downtrend
        result = rsi(data, 14)
        self.assertIsNotNone(result[-1])
        self.assertLess(result[-1], 50)

    def test_atr(self):
        from app.indicators import atr
        highs = [1.1 + i * 0.01 for i in range(20)]
        lows = [1.0 + i * 0.01 for i in range(20)]
        closes = [1.05 + i * 0.01 for i in range(20)]
        result = atr(highs, lows, closes, 14)
        self.assertIsNotNone(result[-1])
        self.assertGreater(result[-1], 0)

    def test_stochastic(self):
        from app.indicators import stochastic
        highs = [1.1 + i * 0.005 for i in range(30)]
        lows = [1.0 + i * 0.005 for i in range(30)]
        closes = [1.05 + i * 0.005 for i in range(30)]
        k, d = stochastic(highs, lows, closes, 14, 3)
        self.assertIsNotNone(k[-1])
        self.assertIsNotNone(d[-1])
        self.assertGreaterEqual(k[-1], 0)
        self.assertLessEqual(k[-1], 100)

    def test_macd(self):
        from app.indicators import macd
        data = list(range(1, 40))
        ml, sl, hist = macd(data, 12, 26, 9)
        self.assertIsNotNone(ml[-1])
        self.assertIsNotNone(hist[-1])

    def test_bollinger(self):
        from app.indicators import bollinger
        data = [1.1 + i * 0.001 for i in range(30)]
        upper, mid, lower = bollinger(data, 20, 2)
        self.assertIsNotNone(upper[-1])
        self.assertIsNotNone(lower[-1])
        self.assertGreater(upper[-1], lower[-1])

    def test_mcginley(self):
        from app.indicators import mcginley_dynamic
        data = [1.1 + i * 0.001 for i in range(20)]
        result = mcginley_dynamic(data, 14)
        self.assertIsNotNone(result[-1])

    def test_candlestick_patterns(self):
        from app.indicators import detect_candlestick_patterns
        # Create a strong bull candle scenario
        highs = [1.10, 1.11, 1.13]
        lows = [1.08, 1.09, 1.10]
        closes = [1.09, 1.10, 1.125]
        patterns = detect_candlestick_patterns(highs, lows, closes, 2)
        self.assertIsInstance(patterns, list)

    def test_trend_strength(self):
        from app.indicators import trend_strength
        # Strong uptrend
        data = list(range(1, 30))
        strength = trend_strength(data, 14)
        self.assertGreater(strength, 0)

    def test_supply_demand_zones(self):
        from app.indicators import find_supply_demand_zones
        feed = MockDataFeed(seed=42)
        hist = feed.get_historical("EUR/USD", bars=40)
        zones = find_supply_demand_zones(hist["highs"], hist["lows"], hist["closes"], 20)
        self.assertIn("demand", zones)
        self.assertIn("supply", zones)


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

    def test_confluence_detail_structure(self):
        hist = self.feed.get_historical("EUR/USD", bars=40)
        result = engine.analyze("EUR/USD", hist["closes"], hist["highs"], hist["lows"])
        if result["confluence_count"] > 0:
            detail = result["confluence_detail"]
            expected_keys = [
                "trend_alignment", "rsi_confirmation", "stochastic_confirmation",
                "macd_confirmation", "bollinger_position", "candlestick_pattern",
                "zone_proximity", "mcginley_confirmation",
            ]
            for key in expected_keys:
                self.assertIn(key, detail)

    def test_trade_setup_has_valid_rr(self):
        """When a trade signal is generated, R:R should be >= 0.8."""
        from app.config import PAIRS
        for pair in PAIRS:
            hist = self.feed.get_historical(pair, bars=40)
            result = engine.analyze(pair, hist["closes"], hist["highs"], hist["lows"])
            if result["trade"]:
                self.assertGreaterEqual(result["trade"]["rr_ratio"], 0.8)


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

    def test_unknown_pair_raises(self):
        feed = MockDataFeed(seed=42)
        with self.assertRaises(ValueError):
            feed.get_historical("INVALID/PAIR")

    def test_all_pairs_have_data(self):
        from app.config import PAIRS
        feed = MockDataFeed(seed=42)
        for pair in PAIRS:
            hist = feed.get_historical(pair, bars=40)
            self.assertEqual(len(hist["closes"]), 40)
            price = feed.get_current_price(pair)
            self.assertGreater(price["mid"], 0)


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

    def test_short_pnl_calculation(self):
        broker = MockBroker()
        result = broker.open_position("EUR/USD", "SHORT", 1.1500, 1.1550, 1.1400, 10000)
        order_id = result["order_id"]
        close = broker.close_position(order_id, 1.1450, "TEST")
        self.assertGreater(close["pnl_pips"], 0)  # SHORT in profit when price falls

    def test_close_already_closed(self):
        broker = MockBroker()
        result = broker.open_position("EUR/USD", "LONG", 1.1500, 1.1450, 1.1600, 10000)
        order_id = result["order_id"]
        broker.close_position(order_id, 1.1550, "TEST")
        second_close = broker.close_position(order_id, 1.1550, "TEST")
        self.assertEqual(second_close["status"], "ERROR")

    def test_close_nonexistent_order(self):
        broker = MockBroker()
        result = broker.close_position("FAKE-ID", 1.1500, "TEST")
        self.assertEqual(result["status"], "ERROR")

    def test_get_open_positions(self):
        broker = MockBroker()
        broker.open_position("EUR/USD", "LONG", 1.1500, 1.1450, 1.1600, 10000)
        broker.open_position("GBP/USD", "SHORT", 1.3400, 1.3450, 1.3300, 5000)
        open_pos = broker.get_open_positions()
        self.assertEqual(len(open_pos), 2)


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

    def test_update_position(self):
        from app import state
        pos = {"order_id": "TEST-002", "pair": "EUR/USD", "trailing_stop_active": False}
        state.add_position(pos)
        state.update_position("TEST-002", {"trailing_stop_active": True, "trailing_stop_price": 1.1480})
        loaded = state.load_positions()
        self.assertTrue(loaded["positions"][0]["trailing_stop_active"])
        self.assertEqual(loaded["positions"][0]["trailing_stop_price"], 1.1480)

    def test_monitoring_event_limit(self):
        from app import state
        for i in range(250):
            state.save_monitoring_event({"time": f"2026-03-16T{i:05d}", "type": "CHECK"})
        loaded = state.load_monitoring()
        self.assertLessEqual(len(loaded["events"]), 200)

    def test_circuit_breaker_not_tripped(self):
        from app import state
        is_tripped, pnl, threshold = state.check_circuit_breaker()
        self.assertFalse(is_tripped)
        self.assertEqual(pnl, 0)

    def test_circuit_breaker_tripped(self):
        from app import state
        from datetime import datetime, timezone
        # Simulate large daily loss
        today_str = datetime.now(timezone.utc).isoformat()
        state.save_trade({"pair": "EUR/USD", "pnl_usd": -350.0, "closed_at": today_str})
        is_tripped, pnl, threshold = state.check_circuit_breaker()
        self.assertTrue(is_tripped)
        self.assertLess(pnl, 0)

    def test_get_daily_pnl(self):
        from app import state
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).isoformat()
        state.save_trade({"pair": "EUR/USD", "pnl_usd": 25.0, "closed_at": today_str})
        state.save_trade({"pair": "GBP/USD", "pnl_usd": -10.0, "closed_at": today_str})
        pnl, count = state.get_daily_pnl()
        self.assertEqual(pnl, 15.0)
        self.assertEqual(count, 2)

    def test_build_dashboard_data(self):
        from app import state
        dashboard = state.build_dashboard_data()
        self.assertIn("summary", dashboard)
        self.assertIn("equity_curve", dashboard)
        self.assertIn("pair_pnl", dashboard)
        self.assertIn("close_reasons", dashboard)
        self.assertIn("signals", dashboard)
        self.assertIn("positions", dashboard)

    def test_equity_curve_with_trades(self):
        from app import state
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).isoformat()
        state.save_trade({"pair": "EUR/USD", "pnl_usd": 50.0, "closed_at": today})
        state.save_trade({"pair": "GBP/USD", "pnl_usd": -20.0, "closed_at": today})
        dashboard = state.build_dashboard_data()
        curve = dashboard["equity_curve"]
        self.assertEqual(len(curve), 3)  # Start + 2 trades
        self.assertEqual(curve[0]["equity"], 10000)
        self.assertEqual(curve[1]["equity"], 10050)
        self.assertEqual(curve[2]["equity"], 10030)


class TestPrognosis(unittest.TestCase):
    """Test the prognosis module."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="forex_test_prognosis_")
        _setup_temp_state(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_prognosis_no_positions(self):
        from app.prognosis import generate_prognosis
        feed = MockDataFeed(seed=42)
        report = generate_prognosis(feed)
        self.assertIn("report_time", report)
        self.assertEqual(len(report["positions"]), 0)
        self.assertIn("market_overview", report)
        self.assertEqual(len(report["market_overview"]), 5)

    def test_prognosis_with_positions(self):
        from app import state
        from app.prognosis import generate_prognosis

        # Add a mock position
        pos = {
            "order_id": "MOCK-TEST1",
            "pair": "EUR/USD",
            "direction": "SHORT",
            "entry_price": 1.1500,
            "stop_loss": 1.1550,
            "take_profit": 1.1400,
            "units": 10000,
            "entry_confluence": 5,
            "entry_trend": "STRONG_DOWN",
            "entry_trend_strength": 45,
            "trailing_stop_active": False,
            "trailing_stop_price": None,
            "monitoring_history": [],
        }
        state.add_position(pos)

        feed = MockDataFeed(seed=42)
        report = generate_prognosis(feed)
        self.assertEqual(len(report["positions"]), 1)

        p = report["positions"][0]
        self.assertEqual(p["pair"], "EUR/USD")
        self.assertIn(p["recommendation"], ["HOLD", "TIGHTEN", "EXIT"])
        self.assertIn("confidence", p)
        self.assertGreaterEqual(p["confidence"], 0)
        self.assertLessEqual(p["confidence"], 100)
        self.assertIn("reasons", p)
        self.assertGreater(len(p["reasons"]), 0)

    def test_prognosis_circuit_breaker_status(self):
        from app.prognosis import generate_prognosis
        feed = MockDataFeed(seed=42)
        report = generate_prognosis(feed)
        self.assertIn("circuit_breaker", report)
        self.assertFalse(report["circuit_breaker"]["is_tripped"])

    def test_prognosis_market_overview(self):
        from app.prognosis import generate_prognosis
        feed = MockDataFeed(seed=42)
        report = generate_prognosis(feed)
        overview = report["market_overview"]
        self.assertEqual(len(overview), 5)
        for item in overview:
            self.assertIn("pair", item)
            self.assertIn("signal", item)
            self.assertIn("confluence", item)


class TestCircuitBreaker(unittest.TestCase):
    """Test circuit breaker integration in scanner and monitor."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="forex_test_cb_")
        _setup_temp_state(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_scanner_blocked_by_circuit_breaker(self):
        from app import state
        from app.scanner import morning_scan
        from datetime import datetime, timezone

        # Trip the circuit breaker
        today = datetime.now(timezone.utc).isoformat()
        state.save_trade({"pair": "EUR/USD", "pnl_usd": -350.0, "closed_at": today})

        feed = MockDataFeed(seed=42)
        broker = MockBroker()
        result = morning_scan(feed, broker)

        self.assertTrue(result.get("circuit_breaker"))
        self.assertEqual(result["positions_opened"], 0)
        self.assertEqual(result["pairs_analyzed"], 0)

    def test_monitor_closes_on_circuit_breaker(self):
        from app import state
        from app.monitor import monitor_positions
        from datetime import datetime, timezone

        # Open a position
        pos = {
            "order_id": "MOCK-CB01",
            "pair": "EUR/USD",
            "direction": "LONG",
            "entry_price": 1.1500,
            "stop_loss": 1.1450,
            "take_profit": 1.1600,
            "units": 10000,
            "entry_confluence": 5,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        state.add_position(pos)

        # Trip the circuit breaker
        today = datetime.now(timezone.utc).isoformat()
        state.save_trade({"pair": "GBP/USD", "pnl_usd": -350.0, "closed_at": today})

        feed = MockDataFeed(seed=42)
        broker = MockBroker()
        # Load position into broker
        broker._orders["MOCK-CB01"] = {
            "order_id": "MOCK-CB01", "pair": "EUR/USD", "direction": "LONG",
            "entry_price": 1.1500, "stop_loss": 1.1450, "take_profit": 1.1600,
            "units": 10000, "status": "OPEN", "opened_at": pos["opened_at"],
            "closed_at": None, "exit_price": None,
            "pnl_pips": None, "pnl_usd": None, "close_reason": None,
        }

        result = monitor_positions(feed, broker)
        self.assertTrue(result.get("circuit_breaker"))
        self.assertGreater(len(result["closed_positions"]), 0)

        # Verify position was removed from state
        remaining = state.load_positions()
        self.assertEqual(len(remaining["positions"]), 0)


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
        self.assertIn("equity_curve", dashboard)
        self.assertIn("pair_pnl", dashboard)

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

    def test_full_day_with_prognosis(self):
        """Test that prognosis works within the pipeline."""
        from app import state
        from app.scanner import morning_scan
        from app.prognosis import generate_prognosis

        feed = MockDataFeed(seed=42)
        broker = MockBroker()

        # Scan first
        scan_result = morning_scan(feed, broker)

        # Run prognosis
        feed_prog = MockDataFeed(seed=42)
        report = generate_prognosis(feed_prog)

        self.assertIn("report_time", report)
        self.assertIn("market_overview", report)
        self.assertEqual(len(report["market_overview"]), 5)

        # Prognosis position count should match open positions
        open_count = len(state.load_positions().get("positions", []))
        self.assertEqual(len(report["positions"]), open_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
