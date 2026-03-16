"""
Signal Engine — the core analysis logic.
Refactored from forex_engine_v2.py to be modular and reusable.
"""
from app import indicators as ind
from app.config import (
    MIN_CONFLUENCE, MIN_TREND_STRENGTH,
    ATR_SL_MULTIPLIER, ATR_TP_BASE, ATR_TP_STRONG, ATR_TP_GOOD,
    PIP_VALUES,
)


def analyze(pair_name, closes, highs, lows, pip_value=None):
    """
    Run full confluence analysis on a pair.

    Returns dict with:
      - signal: "NO TRADE" or "MODERATE LONG" / "GOOD SHORT" / "STRONG LONG" etc.
      - direction: "LONG" / "SHORT" / None
      - confluence_count: int (0-8)
      - confluence_detail: dict of 8 factors → bool
      - trade: dict with entry/SL/TP or None
      - trend, trend_strength, details, indicators
    """
    if pip_value is None:
        pip_value = PIP_VALUES.get(pair_name, 0.0001)

    n = len(closes)
    if n < 20:
        return _no_trade(pair_name, "Insufficient data (need 20+ bars)")

    latest = n - 1
    prev = n - 2

    # Calculate all indicators
    sma_10 = ind.sma(closes, 10)
    sma_20 = ind.sma(closes, 20)
    sma_40 = ind.sma(closes, min(40, n))
    ema_9 = ind.ema(closes, 9)
    ema_21 = ind.ema(closes, 21)
    mcg = ind.mcginley_dynamic(closes, 14)
    rsi_vals = ind.rsi(closes, 14)
    macd_line, macd_sig, macd_hist = ind.macd(closes, 12, 26, 9)
    bb_upper, bb_mid, bb_lower = ind.bollinger(closes, 20, 2)
    atr_vals = ind.atr(highs, lows, closes, 14)
    stoch_k, stoch_d = ind.stochastic(highs, lows, closes, 14, 3)
    zones = ind.find_supply_demand_zones(highs, lows, closes, 20)
    t_strength = ind.trend_strength(closes, 14)
    candle_patterns = ind.detect_candlestick_patterns(highs, lows, closes, latest)

    # Step 1: Determine dominant trend
    trend, trend_score = _determine_trend(sma_10, sma_20, sma_40, closes, latest)

    # Map trend to direction
    if trend_score <= -1:
        direction = "SHORT"
    elif trend_score >= 1:
        direction = "LONG"
    else:
        return _no_trade(pair_name, "Market is ranging — no clear trend",
                         trend=trend, trend_strength=t_strength)

    if t_strength < MIN_TREND_STRENGTH:
        return _no_trade(pair_name, f"Trend strength too low ({t_strength:.0f}/100)",
                         trend=trend, trend_strength=t_strength)

    # Step 2: Score 8 confluence factors
    confluence, details = _score_confluence(
        direction, latest, prev, closes,
        ema_9, ema_21, mcg, rsi_vals, stoch_k, stoch_d,
        macd_hist, bb_upper, bb_lower, candle_patterns,
        zones, pip_value
    )

    conf_count = sum(1 for v in confluence.values() if v)

    if conf_count < MIN_CONFLUENCE:
        return {
            "pair": pair_name, "signal": "NO TRADE", "direction": None,
            "reason": f"Insufficient confluence ({conf_count}/8, need {MIN_CONFLUENCE}+)",
            "trend": trend, "trend_strength": t_strength,
            "confluence_count": conf_count, "confluence_detail": confluence,
            "details": details, "trade": None,
            "indicators": _build_indicator_snapshot(
                latest, sma_10, sma_20, ema_9, ema_21, rsi_vals,
                stoch_k, stoch_d, mcg, atr_vals, bb_upper, bb_lower, macd_hist
            ),
        }

    # Step 3: Build trade setup
    atr_val = atr_vals[latest] if atr_vals[latest] else abs(highs[latest] - lows[latest])
    if conf_count >= 6:
        tp_mult, strength_label = ATR_TP_STRONG, "STRONG"
    elif conf_count >= 5:
        tp_mult, strength_label = ATR_TP_GOOD, "GOOD"
    else:
        tp_mult, strength_label = ATR_TP_BASE, "MODERATE"

    entry = closes[latest]
    sl_dist = atr_val * ATR_SL_MULTIPLIER
    tp_dist = atr_val * tp_mult

    if direction == "LONG":
        stop_loss = entry - sl_dist
        tp1 = entry + tp_dist
    else:
        stop_loss = entry + sl_dist
        tp1 = entry - tp_dist

    return {
        "pair": pair_name,
        "signal": f"{strength_label} {direction}",
        "direction": direction,
        "trend": trend,
        "trend_strength": t_strength,
        "confluence_count": conf_count,
        "confluence_detail": confluence,
        "details": details,
        "trade": {
            "entry": entry,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "atr": atr_val,
            "sl_pips": round(sl_dist / pip_value, 1),
            "tp1_pips": round(tp_dist / pip_value, 1),
            "rr_ratio": round(tp_mult / ATR_SL_MULTIPLIER, 2),
        },
        "indicators": _build_indicator_snapshot(
            latest, sma_10, sma_20, ema_9, ema_21, rsi_vals,
            stoch_k, stoch_d, mcg, atr_vals, bb_upper, bb_lower, macd_hist
        ),
    }


def _determine_trend(sma_10, sma_20, sma_40, closes, idx):
    """Determine dominant trend from MA alignment. Returns (label, score)."""
    if sma_10[idx] and sma_20[idx] and sma_40[idx]:
        if sma_10[idx] < sma_20[idx] < sma_40[idx] and closes[idx] < sma_10[idx]:
            return "STRONG_DOWN", -3
        if sma_10[idx] > sma_20[idx] > sma_40[idx] and closes[idx] > sma_10[idx]:
            return "STRONG_UP", 3
        if sma_10[idx] < sma_20[idx] and closes[idx] < sma_20[idx]:
            return "DOWN", -2
        if sma_10[idx] > sma_20[idx] and closes[idx] > sma_20[idx]:
            return "UP", 2
        if closes[idx] < sma_20[idx]:
            return "WEAK_DOWN", -1
        if closes[idx] > sma_20[idx]:
            return "WEAK_UP", 1
        return "RANGING", 0
    elif sma_10[idx] and sma_20[idx]:
        if sma_10[idx] < sma_20[idx]:
            return "DOWN", -2
        return "UP", 2
    return "UNKNOWN", 0


def _score_confluence(direction, latest, prev, closes,
                      ema_9, ema_21, mcg, rsi_vals, stoch_k, stoch_d,
                      macd_hist, bb_upper, bb_lower, candle_patterns,
                      zones, pip_value):
    """Score all 8 confluence factors. Returns (dict, details_list)."""
    confluence = {
        "trend_alignment": False,
        "rsi_confirmation": False,
        "stochastic_confirmation": False,
        "macd_confirmation": False,
        "bollinger_position": False,
        "candlestick_pattern": False,
        "zone_proximity": False,
        "mcginley_confirmation": False,
    }
    details = []

    # Factor 1: Trend alignment (EMA crossover + McGinley)
    if direction == "LONG":
        if ema_9[latest] and ema_21[latest] and ema_9[latest] > ema_21[latest]:
            confluence["trend_alignment"] = True
            if mcg[latest] and closes[latest] > mcg[latest]:
                details.append(f"TREND: EMA9 > EMA21, price above McGinley ({mcg[latest]:.5f})")
            else:
                details.append("TREND: EMA9 > EMA21 (partial alignment)")
        else:
            details.append("TREND: EMAs not aligned for LONG")
    else:
        if ema_9[latest] and ema_21[latest] and ema_9[latest] < ema_21[latest]:
            confluence["trend_alignment"] = True
            if mcg[latest] and closes[latest] < mcg[latest]:
                details.append(f"TREND: EMA9 < EMA21, price below McGinley ({mcg[latest]:.5f})")
            else:
                details.append("TREND: EMA9 < EMA21 (partial alignment)")
        else:
            details.append("TREND: EMAs not aligned for SHORT")

    # Factor 2: RSI
    if rsi_vals[latest] is not None:
        r = rsi_vals[latest]
        if direction == "LONG" and (25 <= r <= 65 or r < 25):
            confluence["rsi_confirmation"] = True
            details.append(f"RSI: {r:.1f} — {'oversold bounce' if r < 25 else 'room to run up'}")
        elif direction == "SHORT" and (35 <= r <= 75 or r > 75):
            confluence["rsi_confirmation"] = True
            details.append(f"RSI: {r:.1f} — {'overbought drop' if r > 75 else 'room to run down'}")
        else:
            details.append(f"RSI: {r:.1f} — not ideal for {direction}")

    # Factor 3: Stochastic
    if stoch_k[latest] is not None and stoch_d[latest] is not None:
        k, d = stoch_k[latest], stoch_d[latest]
        if direction == "LONG":
            if (stoch_k[prev] is not None and stoch_d[prev] is not None
                    and k > d and stoch_k[prev] <= stoch_d[prev]):
                confluence["stochastic_confirmation"] = True
                details.append(f"STOCH: Bullish crossover K({k:.0f}) > D({d:.0f})")
            elif k < 40 or (k > d and k < 70):
                confluence["stochastic_confirmation"] = True
                details.append(f"STOCH: K={k:.0f} — room to rise")
            else:
                details.append(f"STOCH: K={k:.0f}, D={d:.0f} — no bullish setup")
        else:
            if (stoch_k[prev] is not None and stoch_d[prev] is not None
                    and k < d and stoch_k[prev] >= stoch_d[prev]):
                confluence["stochastic_confirmation"] = True
                details.append(f"STOCH: Bearish crossover K({k:.0f}) < D({d:.0f})")
            elif k > 60 or (k < d and k > 30):
                confluence["stochastic_confirmation"] = True
                details.append(f"STOCH: K={k:.0f} — room to fall")
            else:
                details.append(f"STOCH: K={k:.0f}, D={d:.0f} — no bearish setup")

    # Factor 4: MACD histogram
    if macd_hist[latest] is not None and macd_hist[prev] is not None:
        h_now, h_prev = macd_hist[latest], macd_hist[prev]
        if direction == "LONG" and (h_now > h_prev or h_now > 0):
            confluence["macd_confirmation"] = True
            details.append(f"MACD: Histogram {'rising' if h_now > h_prev else 'positive'} ({h_now:.6f})")
        elif direction == "SHORT" and (h_now < h_prev or h_now < 0):
            confluence["macd_confirmation"] = True
            details.append(f"MACD: Histogram {'falling' if h_now < h_prev else 'negative'} ({h_now:.6f})")
        else:
            details.append(f"MACD: Histogram not confirming {direction}")

    # Factor 5: Bollinger position
    if bb_lower[latest] and bb_upper[latest]:
        bb_range = bb_upper[latest] - bb_lower[latest]
        if bb_range > 0:
            bb_pos = (closes[latest] - bb_lower[latest]) / bb_range
            if direction == "LONG" and bb_pos < 0.5:
                confluence["bollinger_position"] = True
                details.append(f"BB: Price in lower zone ({bb_pos:.0%})")
            elif direction == "SHORT" and bb_pos > 0.5:
                confluence["bollinger_position"] = True
                details.append(f"BB: Price in upper zone ({bb_pos:.0%})")
            else:
                details.append(f"BB: Price at {bb_pos:.0%} — not ideal for {direction}")

    # Factor 6: Candlestick pattern
    bull_patterns = ["BULLISH_PIN_BAR", "BULLISH_ENGULFING", "STRONG_BULL_CANDLE"]
    bear_patterns = ["BEARISH_PIN_BAR", "BEARISH_ENGULFING", "STRONG_BEAR_CANDLE"]
    if direction == "LONG":
        if any(p in candle_patterns for p in bull_patterns) or "DOJI" in candle_patterns:
            confluence["candlestick_pattern"] = True
            details.append(f"CANDLE: {', '.join(candle_patterns) or 'DOJI'}")
        else:
            details.append("CANDLE: No bullish pattern")
    else:
        if any(p in candle_patterns for p in bear_patterns) or "DOJI" in candle_patterns:
            confluence["candlestick_pattern"] = True
            details.append(f"CANDLE: {', '.join(candle_patterns) or 'DOJI'}")
        else:
            details.append("CANDLE: No bearish pattern")

    # Factor 7: Supply/demand zone
    if direction == "LONG":
        in_zone, _ = ind.price_in_zone(closes[latest], zones, "demand", pip_value * 20)
    else:
        in_zone, _ = ind.price_in_zone(closes[latest], zones, "supply", pip_value * 20)
    if in_zone:
        confluence["zone_proximity"] = True
        details.append(f"ZONE: Price near {'demand' if direction == 'LONG' else 'supply'} zone")
    else:
        details.append("ZONE: No relevant zone nearby")

    # Factor 8: McGinley dynamic
    if mcg[latest] and mcg[prev]:
        if direction == "LONG" and mcg[latest] > mcg[prev] and closes[latest] > mcg[latest]:
            confluence["mcginley_confirmation"] = True
            details.append(f"McGINLEY: Rising & price above ({mcg[latest]:.5f})")
        elif direction == "SHORT" and mcg[latest] < mcg[prev] and closes[latest] < mcg[latest]:
            confluence["mcginley_confirmation"] = True
            details.append(f"McGINLEY: Falling & price below ({mcg[latest]:.5f})")
        else:
            details.append(f"McGINLEY: Not confirming {direction}")

    return confluence, details


def _build_indicator_snapshot(idx, sma_10, sma_20, ema_9, ema_21, rsi_vals,
                              stoch_k, stoch_d, mcg, atr_vals, bb_upper, bb_lower, macd_hist):
    """Build a snapshot of current indicator values."""
    def safe(arr):
        return arr[idx] if idx < len(arr) and arr[idx] is not None else None
    return {
        "sma_10": safe(sma_10), "sma_20": safe(sma_20),
        "ema_9": safe(ema_9), "ema_21": safe(ema_21),
        "rsi": safe(rsi_vals), "stoch_k": safe(stoch_k), "stoch_d": safe(stoch_d),
        "mcginley": safe(mcg), "atr": safe(atr_vals),
        "bb_upper": safe(bb_upper), "bb_lower": safe(bb_lower),
        "macd_hist": safe(macd_hist),
    }


def _no_trade(pair_name, reason, trend="UNKNOWN", trend_strength=0):
    return {
        "pair": pair_name, "signal": "NO TRADE", "direction": None,
        "reason": reason, "trend": trend, "trend_strength": trend_strength,
        "confluence_count": 0, "confluence_detail": {}, "details": [reason],
        "trade": None, "indicators": {},
    }
