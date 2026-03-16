"""
Data Feed — provides market data to the engine.

MockDataFeed: generates realistic simulated price action for paper trading.
OandaDataFeed: (future) connects to OANDA v20 API for live data.

Both implement the same interface:
  - get_historical(pair, bars=40) → dict with closes, highs, lows lists
  - get_current_price(pair) → dict with bid, ask, mid
"""
import json
import math
import random
import hashlib
from datetime import datetime, timedelta


class MockDataFeed:
    """
    Simulates realistic forex price data using the v2 engine's historical data
    as a base, then generating intraday ticks with controlled drift and volatility.
    """

    # Base prices from the v2 engine's last known values (Mar 13, 2026)
    BASE_PRICES = {
        "EUR/USD": {"price": 1.1492, "trend": "down", "volatility": 0.0035, "pip": 0.0001},
        "GBP/USD": {"price": 1.3360, "trend": "sideways", "volatility": 0.0028, "pip": 0.0001},
        "USD/JPY": {"price": 157.84, "trend": "up", "volatility": 0.45, "pip": 0.01},
        "AUD/USD": {"price": 0.6218, "trend": "down", "volatility": 0.0022, "pip": 0.0001},
        "USD/CHF": {"price": 0.7870, "trend": "up", "volatility": 0.0025, "pip": 0.0001},
    }

    # Full historical data from v2 engine (40 bars daily)
    HISTORICAL = {
        "EUR/USD": {
            "closes": [1.2380, 1.2365, 1.2350, 1.2340, 1.2325, 1.2310, 1.2295, 1.2280,
                       1.2270, 1.2255, 1.2245, 1.2230, 1.2220, 1.2205, 1.2195,
                       1.2180, 1.2165, 1.2142, 1.2098, 1.2075, 1.2050, 1.2020, 1.1985,
                       1.1960, 1.1935, 1.1905, 1.1880, 1.1855, 1.1830, 1.1800,
                       1.1765, 1.1740, 1.1710, 1.1685, 1.1650, 1.1620, 1.1580, 1.1545, 1.1510, 1.1492],
            "highs": [1.2410, 1.2395, 1.2382, 1.2370, 1.2358, 1.2342, 1.2328, 1.2312,
                      1.2300, 1.2288, 1.2275, 1.2262, 1.2250, 1.2238, 1.2225,
                      1.2210, 1.2195, 1.2178, 1.2145, 1.2110, 1.2082, 1.2058, 1.2025,
                      1.1998, 1.1968, 1.1940, 1.1912, 1.1888, 1.1860, 1.1835,
                      1.1800, 1.1772, 1.1748, 1.1720, 1.1690, 1.1658, 1.1618, 1.1582, 1.1548, 1.1530],
            "lows": [1.2355, 1.2338, 1.2322, 1.2310, 1.2298, 1.2282, 1.2268, 1.2252,
                     1.2242, 1.2228, 1.2218, 1.2202, 1.2192, 1.2178, 1.2168,
                     1.2155, 1.2130, 1.2105, 1.2060, 1.2038, 1.2015, 1.1982, 1.1948,
                     1.1920, 1.1898, 1.1868, 1.1845, 1.1820, 1.1795, 1.1758,
                     1.1728, 1.1700, 1.1672, 1.1648, 1.1612, 1.1575, 1.1540, 1.1505, 1.1470, 1.1458],
        },
        "GBP/USD": {
            "closes": [1.3680, 1.3668, 1.3655, 1.3645, 1.3635, 1.3620, 1.3610, 1.3600,
                       1.3592, 1.3585, 1.3578, 1.3572, 1.3568, 1.3565, 1.3560,
                       1.3580, 1.3565, 1.3548, 1.3520, 1.3505, 1.3488, 1.3470, 1.3452,
                       1.3440, 1.3425, 1.3412, 1.3400, 1.3388, 1.3375, 1.3365,
                       1.3380, 1.3395, 1.3410, 1.3425, 1.3408, 1.3390, 1.3375, 1.3365, 1.3360, 1.3360],
            "highs": [1.3712, 1.3698, 1.3685, 1.3675, 1.3665, 1.3652, 1.3640, 1.3630,
                      1.3622, 1.3615, 1.3608, 1.3600, 1.3595, 1.3592, 1.3588,
                      1.3612, 1.3598, 1.3580, 1.3555, 1.3535, 1.3520, 1.3500, 1.3485,
                      1.3470, 1.3458, 1.3442, 1.3430, 1.3415, 1.3405, 1.3398,
                      1.3415, 1.3428, 1.3440, 1.3455, 1.3438, 1.3418, 1.3402, 1.3390, 1.3385, 1.3388],
            "lows": [1.3652, 1.3640, 1.3628, 1.3618, 1.3608, 1.3592, 1.3582, 1.3572,
                     1.3565, 1.3558, 1.3550, 1.3545, 1.3540, 1.3538, 1.3535,
                     1.3548, 1.3530, 1.3510, 1.3485, 1.3470, 1.3455, 1.3438, 1.3420,
                     1.3408, 1.3392, 1.3378, 1.3365, 1.3355, 1.3342, 1.3330,
                     1.3348, 1.3362, 1.3378, 1.3395, 1.3375, 1.3358, 1.3345, 1.3335, 1.3328, 1.3325],
        },
        "USD/JPY": {
            "closes": [149.20, 149.45, 149.70, 149.95, 150.20, 150.50, 150.80, 151.05,
                       151.30, 151.55, 151.75, 151.95, 152.10, 152.15, 152.18,
                       152.20, 152.55, 152.90, 153.30, 153.65, 153.95, 154.30, 154.70,
                       155.05, 155.40, 155.75, 156.10, 156.45, 156.80, 157.10,
                       157.00, 156.85, 157.20, 157.55, 157.85, 158.10, 158.40, 158.20, 157.95, 157.84],
            "highs": [149.50, 149.75, 150.00, 150.25, 150.50, 150.80, 151.10, 151.35,
                      151.60, 151.85, 152.05, 152.25, 152.40, 152.45, 152.48,
                      152.50, 152.85, 153.20, 153.60, 153.95, 154.25, 154.60, 155.00,
                      155.35, 155.70, 156.05, 156.40, 156.75, 157.10, 157.40,
                      157.30, 157.15, 157.50, 157.85, 158.15, 158.40, 158.70, 158.50, 158.25, 158.20],
            "lows": [148.90, 149.15, 149.40, 149.65, 149.90, 150.20, 150.50, 150.75,
                     151.00, 151.25, 151.45, 151.65, 151.80, 151.85, 151.88,
                     151.90, 152.25, 152.60, 153.00, 153.35, 153.65, 154.00, 154.40,
                     154.75, 155.10, 155.45, 155.80, 156.15, 156.50, 156.80,
                     156.70, 156.55, 156.90, 157.25, 157.55, 157.80, 158.10, 157.90, 157.65, 157.50],
        },
        "AUD/USD": {
            "closes": [0.6520, 0.6512, 0.6502, 0.6495, 0.6488, 0.6478, 0.6470, 0.6462,
                       0.6455, 0.6448, 0.6440, 0.6435, 0.6430, 0.6428, 0.6425,
                       0.6420, 0.6405, 0.6388, 0.6370, 0.6355, 0.6340, 0.6325, 0.6310,
                       0.6298, 0.6285, 0.6270, 0.6260, 0.6248, 0.6240, 0.6235,
                       0.6250, 0.6260, 0.6272, 0.6265, 0.6248, 0.6235, 0.6225, 0.6220, 0.6218, 0.6218],
            "highs": [0.6548, 0.6540, 0.6530, 0.6522, 0.6515, 0.6505, 0.6498, 0.6490,
                      0.6482, 0.6475, 0.6468, 0.6462, 0.6458, 0.6455, 0.6452,
                      0.6448, 0.6432, 0.6418, 0.6398, 0.6382, 0.6368, 0.6352, 0.6340,
                      0.6325, 0.6312, 0.6298, 0.6288, 0.6275, 0.6268, 0.6265,
                      0.6278, 0.6288, 0.6298, 0.6292, 0.6275, 0.6262, 0.6250, 0.6245, 0.6240, 0.6238],
            "lows": [0.6495, 0.6485, 0.6475, 0.6468, 0.6460, 0.6452, 0.6442, 0.6435,
                     0.6428, 0.6420, 0.6415, 0.6408, 0.6402, 0.6400, 0.6398,
                     0.6395, 0.6378, 0.6360, 0.6342, 0.6328, 0.6312, 0.6298, 0.6282,
                     0.6270, 0.6258, 0.6245, 0.6232, 0.6220, 0.6212, 0.6205,
                     0.6218, 0.6232, 0.6248, 0.6240, 0.6222, 0.6208, 0.6198, 0.6195, 0.6192, 0.6190],
        },
        "USD/CHF": {
            "closes": [0.7510, 0.7522, 0.7535, 0.7545, 0.7558, 0.7568, 0.7580, 0.7590,
                       0.7600, 0.7608, 0.7612, 0.7615, 0.7618, 0.7619, 0.7620,
                       0.7620, 0.7640, 0.7655, 0.7670, 0.7688, 0.7705, 0.7720, 0.7738,
                       0.7755, 0.7770, 0.7788, 0.7805, 0.7820, 0.7835, 0.7850,
                       0.7840, 0.7830, 0.7845, 0.7860, 0.7875, 0.7890, 0.7905, 0.7895, 0.7880, 0.7870],
            "highs": [0.7535, 0.7548, 0.7560, 0.7572, 0.7585, 0.7595, 0.7608, 0.7618,
                      0.7628, 0.7635, 0.7640, 0.7642, 0.7645, 0.7645, 0.7648,
                      0.7645, 0.7665, 0.7680, 0.7698, 0.7715, 0.7730, 0.7748, 0.7765,
                      0.7780, 0.7798, 0.7815, 0.7830, 0.7848, 0.7862, 0.7878,
                      0.7868, 0.7858, 0.7872, 0.7888, 0.7902, 0.7918, 0.7930, 0.7920, 0.7908, 0.7898],
            "lows": [0.7488, 0.7500, 0.7512, 0.7522, 0.7535, 0.7545, 0.7558, 0.7568,
                     0.7578, 0.7585, 0.7590, 0.7592, 0.7595, 0.7595, 0.7598,
                     0.7598, 0.7618, 0.7632, 0.7648, 0.7662, 0.7678, 0.7695, 0.7712,
                     0.7728, 0.7745, 0.7760, 0.7778, 0.7795, 0.7810, 0.7825,
                     0.7815, 0.7805, 0.7820, 0.7835, 0.7850, 0.7865, 0.7880, 0.7870, 0.7855, 0.7845],
        },
    }

    def __init__(self, seed=None):
        """Initialize with optional seed for reproducible simulations."""
        self._seed = seed
        if seed is not None:
            random.seed(seed)
        self._intraday_cache = {}

    def _date_seed(self, pair, date_str=None):
        """Create a deterministic seed from pair + date so same day = same prices."""
        if date_str is None:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
        h = hashlib.md5(f"{pair}:{date_str}".encode()).hexdigest()
        return int(h[:8], 16)

    def get_historical(self, pair, bars=40):
        """
        Get historical daily OHLC data.
        Appends simulated new bars beyond the base 40 if today is past Mar 13.
        """
        if pair not in self.HISTORICAL:
            raise ValueError(f"Unknown pair: {pair}")

        base = self.HISTORICAL[pair]
        closes = list(base["closes"])
        highs = list(base["highs"])
        lows = list(base["lows"])

        # Extend with simulated bars for days after Mar 13, 2026
        base_date = datetime(2026, 3, 13)
        today = datetime.utcnow()
        extra_days = max(0, (today - base_date).days)

        bp = self.BASE_PRICES[pair]
        rng = random.Random(self._date_seed(pair, "extend"))

        for d in range(1, extra_days + 1):
            dt = base_date + timedelta(days=d)
            if dt.weekday() >= 5:  # skip weekends
                continue
            prev_close = closes[-1]
            drift = -0.0002 if bp["trend"] == "down" else (0.0002 if bp["trend"] == "up" else 0)
            if bp["pip"] == 0.01:  # JPY pairs
                drift *= 100
            move = drift + rng.gauss(0, bp["volatility"] * 0.5)
            new_close = prev_close + move
            new_high = new_close + abs(rng.gauss(0, bp["volatility"] * 0.3))
            new_low = new_close - abs(rng.gauss(0, bp["volatility"] * 0.3))
            if new_high < new_close:
                new_high = new_close + bp["pip"] * 5
            if new_low > new_close:
                new_low = new_close - bp["pip"] * 5
            closes.append(round(new_close, 5 if bp["pip"] == 0.0001 else 2))
            highs.append(round(new_high, 5 if bp["pip"] == 0.0001 else 2))
            lows.append(round(new_low, 5 if bp["pip"] == 0.0001 else 2))

        # Return last `bars` bars
        n = min(bars, len(closes))
        return {
            "closes": closes[-n:],
            "highs": highs[-n:],
            "lows": lows[-n:],
        }

    def get_current_price(self, pair):
        """
        Get current simulated price with realistic bid/ask spread.
        Deterministic per pair+minute so repeated calls within same minute are stable.
        """
        if pair not in self.BASE_PRICES:
            raise ValueError(f"Unknown pair: {pair}")

        bp = self.BASE_PRICES[pair]
        now = datetime.utcnow()
        seed = self._date_seed(pair, now.strftime("%Y-%m-%d-%H-%M"))
        rng = random.Random(seed)

        # Get latest historical close as base
        hist = self.get_historical(pair, bars=1)
        base_price = hist["closes"][-1]

        # Add intraday noise
        noise = rng.gauss(0, bp["volatility"] * 0.1)
        mid = base_price + noise

        # Spread: 1-3 pips depending on pair
        spread = bp["pip"] * rng.uniform(1.0, 3.0)
        bid = mid - spread / 2
        ask = mid + spread / 2

        return {
            "bid": round(bid, 5 if bp["pip"] == 0.0001 else 3),
            "ask": round(ask, 5 if bp["pip"] == 0.0001 else 3),
            "mid": round(mid, 5 if bp["pip"] == 0.0001 else 3),
            "spread_pips": round(spread / bp["pip"], 1),
            "timestamp": now.isoformat(),
        }

    def simulate_price_movement(self, pair, entry_price, hours=8, direction_bias=None):
        """
        Simulate intraday price path for monitoring.
        Returns list of (timestamp, price) tuples at 30-min intervals.
        """
        bp = self.BASE_PRICES[pair]
        now = datetime.utcnow()
        rng = random.Random(self._date_seed(pair, now.strftime("%Y-%m-%d-sim")))

        points = []
        price = entry_price
        intervals = int(hours * 2)  # 30-min intervals

        for i in range(intervals):
            t = now + timedelta(minutes=30 * i)
            # Random walk with slight trend bias
            drift = 0
            if direction_bias == "LONG":
                drift = bp["volatility"] * 0.02  # slight bullish bias
            elif direction_bias == "SHORT":
                drift = -bp["volatility"] * 0.02

            move = drift + rng.gauss(0, bp["volatility"] * 0.15)
            price += move
            points.append({
                "timestamp": t.isoformat(),
                "price": round(price, 5 if bp["pip"] == 0.0001 else 3),
            })

        return points


class OandaDataFeed:
    """
    Future: OANDA v20 API data feed.
    Implements the same interface as MockDataFeed.
    """

    def __init__(self, api_key, account_id, environment="practice"):
        self.api_key = api_key
        self.account_id = account_id
        self.environment = environment
        # Will use oandapyV20 library when implemented

    def get_historical(self, pair, bars=40):
        raise NotImplementedError("OANDA data feed not yet implemented. Use MockDataFeed.")

    def get_current_price(self, pair):
        raise NotImplementedError("OANDA data feed not yet implemented. Use MockDataFeed.")
