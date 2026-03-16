# Forex Trading Bot

An automated day-trading bot for forex that runs entirely on GitHub Actions — no server required. Uses an 8-factor confluence gate to filter high-probability setups, monitors positions throughout the day, and closes everything before the session ends. Currently runs in **mock mode** (no real money), with an OANDA API integration path ready.

## Live Dashboard

Hosted via GitHub Pages at:
```
https://YOUR_USERNAME.github.io/forex-trader/
```
Auto-refreshes every 30 seconds. Set up under **Settings → Pages → Branch: main, Folder: /docs**.

---

## How It Works

Each weekday the bot runs three phases automatically via GitHub Actions:

| Time (CET) | Action | What it does |
|---|---|---|
| 08:00 | **Scan** | Analyses 5 pairs, opens up to 3 positions |
| Every 15 min (08:00–21:00) | **Monitor** | Checks confluence, trails stops, force-closes on breakdown |
| 12:00 & 16:00 | **Prognosis** | HOLD / TIGHTEN / EXIT recommendation per position |
| 22:00 | **Close** | Exits all remaining open positions |

All state (positions, trades, signals, run history) is committed back to the `data/` folder after every run. The dashboard reads `docs/dashboard_data.json`.

---

## The 8-Factor Confluence Gate

A signal is only taken when **4 or more** of these 8 factors agree on a direction:

1. **Trend Alignment** — EMA 9/21 + McGinley Dynamic all pointing the same way
2. **RSI Confirmation** — RSI(14) in a favorable zone (not overbought for longs, not oversold for shorts)
3. **Stochastic** — K/D crossover or extreme reading confirming direction
4. **MACD Momentum** — Histogram moving in the trade's favour
5. **Bollinger Band Position** — Price has room to move (not stretched against the trade)
6. **Candlestick Pattern** — Pin bar, engulfing, strong momentum candle at entry
7. **Supply/Demand Zone** — Price near an institutional accumulation/distribution zone
8. **McGinley Dynamic** — Adaptive MA confirming trend direction and price position

### Position Sizing & Risk

- ATR-based stop-loss (1.5× ATR) and take-profit (1.2×–2.0× ATR, scaled by confluence strength)
- Position size calculated to risk exactly 1% of capital per trade
- Circuit breaker halts all new trades and force-closes open positions if daily loss exceeds **3%**
- Trailing stop activates when trade is 50% of the way to take-profit

---

## Project Structure

```
forex-trader/
├── main.py                    # CLI entry point — all commands
├── requirements.txt           # No external deps in mock mode
│
├── app/
│   ├── config.py              # All constants, file paths, thresholds
│   ├── data_feed.py           # MockDataFeed (deterministic price data)
│   ├── broker.py              # MockBroker (in-memory order execution)
│   ├── engine.py              # 8-factor confluence analysis engine
│   ├── indicators.py          # EMA, RSI, Stochastic, MACD, Bollinger, ATR, McGinley
│   ├── scanner.py             # Morning scan — finds and opens positions
│   ├── monitor.py             # Intraday monitor — trailing stops, force-close logic
│   ├── closer.py              # Evening close — exits all open positions
│   ├── prognosis.py           # Per-position HOLD/TIGHTEN/EXIT recommendations
│   └── state.py               # JSON state persistence + dashboard data builder
│
├── data/                      # Runtime state (committed by the bot after each run)
│   ├── positions.json
│   ├── trades.json
│   ├── signals.json
│   ├── monitoring.json
│   └── run_history.json
│
├── docs/                      # GitHub Pages — served as the live dashboard
│   ├── index.html             # Dashboard UI (dark theme, SVG charts, run timeline)
│   └── dashboard_data.json    # Generated JSON blob read by the dashboard
│
├── tests/
│   └── test_pipeline.py       # 50 unit tests covering all modules
│
└── .github/workflows/
    └── trading.yml            # Scheduled GitHub Actions workflow
```

---

## Running Locally

No dependencies to install — pure Python stdlib.

```bash
# Full day simulation (scan → monitor → close, deterministic)
python main.py simulate

# Individual commands (as GitHub Actions runs them)
python main.py scan
python main.py monitor
python main.py close
python main.py prognosis
python main.py status

# Regenerate dashboard data from current state
python main.py dashboard

# Run the test suite
python -m unittest tests.test_pipeline -v
```

Serve the dashboard locally:
```bash
cd docs && python -m http.server 8080
# Open http://localhost:8080
```

---

## GitHub Actions Setup

1. Push this repo to GitHub (set to **Private**)
2. Go to **Settings → Actions → General → Workflow permissions** → enable **Read and write permissions**
3. Go to **Settings → Pages** → Branch: `main`, Folder: `/docs` → Save
4. Go to **Actions → Forex Trading Bot → Run workflow** → select `simulate` → confirm it runs cleanly

The bot will then run itself on the schedule above every weekday.

### Free Tier Usage

15-minute monitoring intervals during market hours only (~56 runs/day × ~1 min = ~1,120 min/month). GitHub's free tier provides 2,000 minutes/month — leaves comfortable headroom.

---

## Configuration (`app/config.py`)

| Constant | Default | Description |
|---|---|---|
| `INITIAL_CAPITAL` | `10000.0` | Starting capital in USD |
| `MAX_OPEN_POSITIONS` | `3` | Max simultaneous trades |
| `MIN_CONFLUENCE` | `4` | Minimum factors required to enter |
| `MIN_TREND_STRENGTH` | `20` | Minimum trend strength (0–100) |
| `MAX_DAILY_LOSS_PCT` | `0.03` | Circuit breaker threshold (3%) |
| `RISK_PER_TRADE_PCT` | `0.01` | Risk per trade (1% of capital) |
| `MONITOR_INTERVAL_MINUTES` | `15` | Monitoring frequency |
| `BROKER_MODE` | `mock` | `mock` or `oanda` (env var) |

---

## Roadmap

### Next: OANDA API Integration
- Replace `MockBroker` with `OandaBroker` in `app/broker.py`
- Replace `MockDataFeed` with `OandaDataFeed` in `app/data_feed.py`
- Add `OANDA_API_KEY` and `OANDA_ACCOUNT_ID` as GitHub Actions secrets
- Set `BROKER_MODE=oanda` in `trading.yml`

### Backlog
- [ ] Multi-timeframe confirmation (H1 + H4 alignment)
- [ ] Telegram / email alerts on trade open/close
- [ ] Extended backtest with real historical data (6+ months)
- [ ] Per-pair performance analytics in the dashboard
- [ ] Risk-of-ruin calculator based on live equity curve

---

## Disclaimer

Mock mode only — no real money is traded. This project is for educational purposes. Forex trading involves substantial risk of loss. Past simulated performance is not indicative of future results.
