# Forex Signal Engine v2 — High-Probability Confluence Strategy

A Python-based forex signal engine that uses an 8-factor confluence gate to generate high-probability trade signals. Backtested at **83.3% win rate** (5W / 1L) on 5 major currency pairs.

## Files

- `forex_engine_v2.py` — Signal engine with backtest simulation
- `forex_signal_dashboard_v2.html` — Interactive dashboard with results and current signals

## How It Works

The engine analyzes 5 major pairs (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CHF) and only generates a signal when **4 or more of 8 confluence factors** agree on a trade direction.

### The 8 Confluence Factors

1. **Trend Alignment** — EMA 9/21 + multi-timeframe SMA 10/20/40 must all point the same way
2. **RSI Confirmation** — RSI(14) must be in a favorable zone for the trade direction
3. **Stochastic Double Punch** — K/D crossover or extreme reading confirming direction
4. **MACD Momentum** — Histogram must be moving in the trade's favor
5. **Bollinger Band Position** — Price must have room to move (lower half for longs, upper for shorts)
6. **Candlestick Pattern** — Pin bar, engulfing, or strong momentum candle at entry
7. **Supply/Demand Zones** — Price near an institutional accumulation/distribution zone
8. **McGinley Dynamic** — Adaptive moving average confirming trend direction and price position

### Key Rules

- Never trade counter-trend — all moving averages must align with the trade
- Skip ranging markets — trend strength must be above 20/100
- Don't chase — refuse to enter when oscillators are at extremes against the trade
- Minimum 4/8 confluence before any trade is taken
- ATR-based dynamic stop-loss (1.5x ATR) and take-profit (1.2x–2.0x ATR depending on confluence strength)

## Running the Engine

```bash
python forex_engine_v2.py
```

Outputs full technical analysis for all 5 pairs, confluence breakdown, trade setups, and backtest results.

## Backtest Results (Jan 20 – Mar 13, 2026)

| Metric | v1 (Old) | v2 (Current) |
|--------|----------|--------------|
| Trades | 15 | 6 |
| Win Rate | 40.0% | **83.3%** |
| P&L | -$113.12 | +$66.58 |
| Return | -1.13% | +0.67% |

## Roadmap

- [ ] Connect to live forex API (OANDA / Alpha Vantage) for real-time data
- [ ] Add automated scanning with alert notifications
- [ ] Extended backtest across 6+ months of data
- [ ] Live paper trading phase (2-4 weeks)
- [ ] Explore automated trade execution

## Disclaimer

This is a fictional paper trading simulation for educational purposes only. The win rate is based on a small sample and should not be extrapolated. Forex trading involves substantial risk of loss. Not financial advice.
