"""
Prognosis — evaluates current trade outlook and validity.

For each open position, produces a structured assessment:
  - Is the original signal still valid?
  - What's the projected outcome based on current indicators?
  - Risk/reward snapshot at current price
  - Recommended action (HOLD, TIGHTEN, EXIT)
"""
from datetime import datetime, timezone
from app import engine, state
from app.config import (
    PIP_VALUES, TRAILING_STOP_ACTIVATION_PIPS,
    CONFLUENCE_WARNING_DROP, CONFLUENCE_FORCE_CLOSE,
    INITIAL_CAPITAL, MAX_DAILY_LOSS_PCT,
)


def generate_prognosis(data_feed):
    """
    Generate a full prognosis report for all open positions.

    Returns dict with:
      - report_time: ISO timestamp
      - daily_pnl: float
      - circuit_breaker_status: dict
      - positions: list of position prognosis dicts
      - market_overview: dict with pair-level signal summaries
    """
    report_time = datetime.now(timezone.utc).isoformat()
    positions_data = state.load_positions()
    positions = positions_data.get("positions", [])
    trades_data = state.load_trades()
    all_trades = trades_data.get("trades", [])

    # Daily P&L
    today_str = report_time[:10]
    today_trades = [t for t in all_trades if t.get("closed_at", "")[:10] == today_str]
    realized_pnl = sum(t.get("pnl_usd", 0) for t in today_trades)

    # Circuit breaker status
    is_tripped, daily_pnl, threshold = state.check_circuit_breaker()

    # Overall stats
    total_realized = sum(t.get("pnl_usd", 0) for t in all_trades)
    effective_capital = INITIAL_CAPITAL + total_realized

    position_reports = []

    for pos in positions:
        pair = pos["pair"]
        pip = PIP_VALUES.get(pair, 0.0001)

        # Current price
        price_data = data_feed.get_current_price(pair)
        current_price = price_data["mid"]

        # Current P&L
        entry_price = pos["entry_price"]
        direction = pos["direction"]
        if direction == "LONG":
            pnl_pips = (current_price - entry_price) / pip
        else:
            pnl_pips = (entry_price - current_price) / pip

        pnl_usd = pnl_pips * pip * pos.get("units", 0)

        # Re-run confluence
        hist = data_feed.get_historical(pair, bars=40)
        analysis = engine.analyze(pair, hist["closes"], hist["highs"], hist["lows"], pip)

        current_confluence = analysis.get("confluence_count", 0)
        entry_confluence = pos.get("entry_confluence", pos.get("confluence_at_entry", 0))
        confluence_change = current_confluence - entry_confluence

        # Distance to SL and TP
        sl_price = pos.get("trailing_stop_price") or pos["stop_loss"]
        tp_price = pos["take_profit"]

        if direction == "LONG":
            dist_to_sl_pips = (current_price - sl_price) / pip
            dist_to_tp_pips = (tp_price - current_price) / pip
        else:
            dist_to_sl_pips = (sl_price - current_price) / pip
            dist_to_tp_pips = (current_price - tp_price) / pip

        # Current risk/reward from this point
        rr_current = dist_to_tp_pips / dist_to_sl_pips if dist_to_sl_pips > 0 else 0

        # Trend assessment
        current_trend = analysis.get("trend", "UNKNOWN")
        current_trend_strength = analysis.get("trend_strength", 0)
        entry_trend = pos.get("entry_trend", "UNKNOWN")

        # Determine if signal direction still matches
        signal_direction = analysis.get("direction")
        direction_aligned = signal_direction == direction

        # Momentum check using indicators
        indicators = analysis.get("indicators", {})
        rsi_val = indicators.get("rsi")
        macd_hist_val = indicators.get("macd_hist")

        # Build momentum assessment
        momentum = "NEUTRAL"
        if direction == "LONG":
            if rsi_val and rsi_val > 60 and macd_hist_val and macd_hist_val > 0:
                momentum = "STRONG_FAVORABLE"
            elif rsi_val and rsi_val > 45 and macd_hist_val and macd_hist_val > 0:
                momentum = "FAVORABLE"
            elif rsi_val and rsi_val < 35:
                momentum = "ADVERSE"
            elif macd_hist_val and macd_hist_val < 0:
                momentum = "WEAKENING"
        else:
            if rsi_val and rsi_val < 40 and macd_hist_val and macd_hist_val < 0:
                momentum = "STRONG_FAVORABLE"
            elif rsi_val and rsi_val < 55 and macd_hist_val and macd_hist_val < 0:
                momentum = "FAVORABLE"
            elif rsi_val and rsi_val > 65:
                momentum = "ADVERSE"
            elif macd_hist_val and macd_hist_val > 0:
                momentum = "WEAKENING"

        # Generate recommendation
        recommendation, reasons = _generate_recommendation(
            pnl_pips, confluence_change, current_confluence,
            direction_aligned, momentum, rr_current,
            dist_to_sl_pips, dist_to_tp_pips,
            pos.get("trailing_stop_active", False),
        )

        # Confidence score (0-100)
        confidence = _calculate_confidence(
            current_confluence, direction_aligned,
            momentum, rr_current, current_trend_strength,
        )

        position_reports.append({
            "order_id": pos["order_id"],
            "pair": pair,
            "direction": direction,
            "entry_price": entry_price,
            "current_price": current_price,
            "pnl_pips": round(pnl_pips, 1),
            "pnl_usd": round(pnl_usd, 2),
            "confluence": {
                "at_entry": entry_confluence,
                "current": current_confluence,
                "change": confluence_change,
            },
            "distances": {
                "to_sl_pips": round(dist_to_sl_pips, 1),
                "to_tp_pips": round(dist_to_tp_pips, 1),
                "rr_current": round(rr_current, 2),
            },
            "trend": {
                "at_entry": entry_trend,
                "current": current_trend,
                "strength": round(current_trend_strength, 1),
                "direction_aligned": direction_aligned,
            },
            "momentum": momentum,
            "trailing_stop_active": pos.get("trailing_stop_active", False),
            "recommendation": recommendation,
            "reasons": reasons,
            "confidence": confidence,
            "indicators": {
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "macd_hist": round(macd_hist_val, 6) if macd_hist_val else None,
            },
        })

    # Market overview — scan all pairs for opportunities
    from app.config import PAIRS
    market_overview = []
    for pair in PAIRS:
        hist = data_feed.get_historical(pair, bars=40)
        pip = PIP_VALUES.get(pair, 0.0001)
        analysis = engine.analyze(pair, hist["closes"], hist["highs"], hist["lows"], pip)
        price_data = data_feed.get_current_price(pair)
        market_overview.append({
            "pair": pair,
            "signal": analysis["signal"],
            "direction": analysis.get("direction"),
            "confluence": analysis.get("confluence_count", 0),
            "trend": analysis.get("trend", "UNKNOWN"),
            "trend_strength": round(analysis.get("trend_strength", 0), 1),
            "current_price": price_data["mid"],
        })

    return {
        "report_time": report_time,
        "effective_capital": round(effective_capital, 2),
        "daily_pnl": round(realized_pnl, 2),
        "circuit_breaker": {
            "is_tripped": is_tripped,
            "daily_pnl": daily_pnl,
            "threshold": threshold,
        },
        "positions": position_reports,
        "market_overview": market_overview,
    }


def _generate_recommendation(pnl_pips, conf_change, current_conf,
                              direction_aligned, momentum, rr_current,
                              dist_to_sl, dist_to_tp, trailing_active):
    """Generate trade recommendation with reasons."""
    reasons = []

    # EXIT signals
    if current_conf < CONFLUENCE_FORCE_CLOSE:
        return "EXIT", [f"Confluence critically low ({current_conf}/8)"]

    if not direction_aligned and conf_change <= -CONFLUENCE_WARNING_DROP:
        return "EXIT", [
            f"Signal direction flipped",
            f"Confluence dropped by {abs(conf_change)}",
        ]

    if momentum == "ADVERSE":
        reasons.append("Momentum turning against position")
        if pnl_pips > 0:
            return "TIGHTEN", reasons + ["Consider tightening stop to lock profit"]
        elif pnl_pips < -15:
            return "EXIT", reasons + [f"Losing {abs(pnl_pips):.0f} pips with adverse momentum"]

    # TIGHTEN signals
    if pnl_pips >= TRAILING_STOP_ACTIVATION_PIPS and not trailing_active:
        reasons.append(f"In profit by {pnl_pips:.0f} pips — trailing stop should activate")
        return "TIGHTEN", reasons

    if momentum == "WEAKENING" and pnl_pips > 10:
        reasons.append("Momentum weakening while in profit")
        return "TIGHTEN", reasons

    if conf_change <= -1 and pnl_pips > 0:
        reasons.append(f"Confluence dropped by {abs(conf_change)} but still profitable")
        return "TIGHTEN", reasons

    # HOLD signals
    if direction_aligned and momentum in ("FAVORABLE", "STRONG_FAVORABLE"):
        reasons.append("Signal direction aligned with strong momentum")
        if current_conf >= 5:
            reasons.append(f"High confluence ({current_conf}/8)")
        return "HOLD", reasons

    if direction_aligned and rr_current > 1.5:
        reasons.append(f"Good R:R remaining ({rr_current:.1f}:1)")
        return "HOLD", reasons

    if pnl_pips >= 0 and current_conf >= 4:
        reasons.append("Signal valid, position in profit or breakeven")
        return "HOLD", reasons

    # Default
    if not reasons:
        reasons.append("Position within normal parameters")
    return "HOLD", reasons


def _calculate_confidence(current_conf, direction_aligned, momentum,
                           rr_current, trend_strength):
    """Calculate confidence score (0-100) for the current position."""
    score = 0

    # Confluence factor (0-30)
    score += min(30, current_conf * 4)

    # Direction alignment (0-20)
    if direction_aligned:
        score += 20

    # Momentum (0-20)
    momentum_scores = {
        "STRONG_FAVORABLE": 20,
        "FAVORABLE": 15,
        "NEUTRAL": 8,
        "WEAKENING": 3,
        "ADVERSE": 0,
    }
    score += momentum_scores.get(momentum, 5)

    # Risk/Reward (0-15)
    if rr_current > 2:
        score += 15
    elif rr_current > 1.5:
        score += 12
    elif rr_current > 1:
        score += 8
    elif rr_current > 0.5:
        score += 4

    # Trend strength (0-15)
    score += min(15, trend_strength * 0.15)

    return min(100, round(score))
