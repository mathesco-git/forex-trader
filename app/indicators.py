"""
Technical indicators — extracted from forex_engine_v2.py for reuse.
All functions are pure: they take data arrays and return result arrays.
"""
import math


def sma(data, period):
    """Simple Moving Average"""
    result = [None] * len(data)
    if len(data) < period:
        return result
    for i in range(period - 1, len(data)):
        result[i] = sum(data[i - period + 1:i + 1]) / period
    return result


def ema(data, period):
    """Exponential Moving Average"""
    result = [None] * len(data)
    if len(data) < period:
        return result
    mult = 2 / (period + 1)
    result[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        result[i] = (data[i] - result[i - 1]) * mult + result[i - 1]
    return result


def rsi(data, period=14):
    """Relative Strength Index"""
    result = [None] * len(data)
    deltas = [data[i] - data[i - 1] for i in range(1, len(data))]
    if len(deltas) < period:
        return result
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        result[period] = 100
    else:
        result[period] = 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period, len(deltas)):
        g = max(deltas[i], 0)
        l_val = abs(min(deltas[i], 0))
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l_val) / period
        result[i + 1] = 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return result


def macd(data, fast=12, slow=26, sig=9):
    """MACD (line, signal, histogram)"""
    if len(data) < slow:
        return [None] * len(data), [None] * len(data), [None] * len(data)
    ef = ema(data, fast)
    es = ema(data, slow)
    ml = [None] * len(data)
    for i in range(len(data)):
        if ef[i] is not None and es[i] is not None:
            ml[i] = ef[i] - es[i]
    valid = [(i, v) for i, v in enumerate(ml) if v is not None]
    sl = [None] * len(data)
    if len(valid) >= sig:
        start = valid[sig - 1][0]
        sl[start] = sum(v for _, v in valid[:sig]) / sig
        mult = 2 / (sig + 1)
        for j in range(sig, len(valid)):
            idx = valid[j][0]
            sl[idx] = (ml[idx] - sl[valid[j - 1][0]]) * mult + sl[valid[j - 1][0]]
    hist = [None] * len(data)
    for i in range(len(data)):
        if ml[i] is not None and sl[i] is not None:
            hist[i] = ml[i] - sl[i]
    return ml, sl, hist


def bollinger(data, period=20, std_dev=2):
    """Bollinger Bands (upper, middle, lower)"""
    mid = sma(data, period)
    upper = [None] * len(data)
    lower = [None] * len(data)
    for i in range(period - 1, len(data)):
        s = data[i - period + 1:i + 1]
        m = mid[i]
        std = math.sqrt(sum((x - m) ** 2 for x in s) / period)
        upper[i] = m + std_dev * std
        lower[i] = m - std_dev * std
    return upper, mid, lower


def atr(highs, lows, closes, period=14):
    """Average True Range"""
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        ))
    result = [None] * len(closes)
    if len(trs) >= period:
        result[period - 1] = sum(trs[:period]) / period
        for i in range(period, len(trs)):
            result[i] = (result[i - 1] * (period - 1) + trs[i]) / period
    return result


def stochastic(highs, lows, closes, k_per=14, d_per=3):
    """Stochastic Oscillator (%K, %D)"""
    k_vals = [None] * len(closes)
    for i in range(k_per - 1, len(closes)):
        h = max(highs[i - k_per + 1:i + 1])
        l = min(lows[i - k_per + 1:i + 1])
        k_vals[i] = ((closes[i] - l) / (h - l)) * 100 if h != l else 50
    d_vals = [None] * len(closes)
    valid = [(i, v) for i, v in enumerate(k_vals) if v is not None]
    for j in range(d_per - 1, len(valid)):
        idx = valid[j][0]
        d_vals[idx] = sum(valid[j - d_per + 1 + x][1] for x in range(d_per)) / d_per
    return k_vals, d_vals


def mcginley_dynamic(data, period=14):
    """McGinley Dynamic — adaptive moving average that reduces lag"""
    result = [None] * len(data)
    if len(data) < period:
        return result
    result[period - 1] = sum(data[:period]) / period
    for i in range(period, len(data)):
        prev = result[i - 1]
        ratio = data[i] / prev if prev != 0 else 1
        denominator = period * (ratio ** 4)
        if denominator == 0:
            result[i] = prev
        else:
            result[i] = prev + (data[i] - prev) / denominator
    return result


def detect_candlestick_patterns(highs, lows, closes, idx):
    """Detect candlestick patterns at given index. Returns list of pattern names."""
    patterns = []
    if idx < 2:
        return patterns

    o = closes[idx - 1]  # open approx = prev close
    h = highs[idx]
    l = lows[idx]
    c = closes[idx]
    body = abs(c - o)
    full_range = h - l
    if full_range == 0:
        return patterns

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if lower_wick > body * 2 and upper_wick < body * 0.5 and c > o:
        patterns.append("BULLISH_PIN_BAR")
    if upper_wick > body * 2 and lower_wick < body * 0.5 and c < o:
        patterns.append("BEARISH_PIN_BAR")

    prev_o = closes[idx - 2]
    prev_c = closes[idx - 1]
    prev_body = abs(prev_c - prev_o)
    if c > o and prev_c < prev_o and body > prev_body * 1.2:
        if c > prev_o and o < prev_c:
            patterns.append("BULLISH_ENGULFING")
    if c < o and prev_c > prev_o and body > prev_body * 1.2:
        if c < prev_o and o > prev_c:
            patterns.append("BEARISH_ENGULFING")

    if body < full_range * 0.1:
        patterns.append("DOJI")
    if body > full_range * 0.7:
        if c > o:
            patterns.append("STRONG_BULL_CANDLE")
        else:
            patterns.append("STRONG_BEAR_CANDLE")

    return patterns


def find_supply_demand_zones(highs, lows, closes, lookback=20):
    """Identify supply (resistance) and demand (support) zones."""
    n = len(closes)
    zones = {"demand": [], "supply": []}
    for i in range(2, min(lookback, n - 2)):
        idx = n - 1 - i
        if idx >= 1 and idx < n - 2:
            if lows[idx] < lows[idx - 1] and lows[idx] < lows[idx + 1]:
                if closes[idx + 1] > highs[idx] or (idx + 2 < n and closes[idx + 2] > highs[idx]):
                    zones["demand"].append({
                        "low": lows[idx],
                        "high": max(closes[idx], highs[idx]) * 0.5 + min(closes[idx], lows[idx]) * 0.5 + (highs[idx] - lows[idx]) * 0.3,
                        "strength": abs(closes[min(idx + 2, n - 1)] - lows[idx])
                    })
            if highs[idx] > highs[idx - 1] and highs[idx] > highs[idx + 1]:
                if closes[idx + 1] < lows[idx] or (idx + 2 < n and closes[idx + 2] < lows[idx]):
                    zones["supply"].append({
                        "low": min(closes[idx], lows[idx]) * 0.5 + max(closes[idx], highs[idx]) * 0.5 - (highs[idx] - lows[idx]) * 0.3,
                        "high": highs[idx],
                        "strength": abs(highs[idx] - closes[min(idx + 2, n - 1)])
                    })
    return zones


def price_in_zone(price, zones, zone_type, tolerance=0.0):
    """Check if price is near a supply or demand zone."""
    for z in zones[zone_type]:
        zone_range = z["high"] - z["low"]
        tol = zone_range * 0.5 + tolerance
        if z["low"] - tol <= price <= z["high"] + tol:
            return True, z["strength"]
    return False, 0


def trend_strength(closes, period=14):
    """Measure trend strength (0-100). >25 = trending, >40 = strong."""
    if len(closes) < period + 1:
        return 0
    up_days = 0
    total_move = 0
    for i in range(len(closes) - period, len(closes)):
        if closes[i] > closes[i - 1]:
            up_days += 1
        total_move += abs(closes[i] - closes[i - 1])
    direction_ratio = abs(up_days - (period - up_days)) / period
    if total_move == 0:
        return 0
    net_move = abs(closes[-1] - closes[-1 - period])
    efficiency = net_move / total_move
    return min(100, (direction_ratio * 50 + efficiency * 50))
