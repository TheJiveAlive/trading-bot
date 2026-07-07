# Robinhood small-cap signal bot

Scans US small-cap stocks ($1–$20, NASDAQ/NYSE) several times a day for
insider buying (SEC Form 4), sector momentum, revenue/earnings health and
news flow. Buys whole shares roughly weekly from a £100/month (~$127) budget,
holds days-to-weeks, and manages exits (trailing stop / take profit) on every
scan.

## Commands

```
python3 run.py scan     # one full cycle: deposit check, exits, signals, maybe buy
python3 run.py status   # cash, positions, recent trades and decisions
```

Every scan writes a log to `logs/` and records every decision (including
decisions *not* to trade, and why) in `data/ledger.db` (SQLite).

## Modes

Set `"mode"` in `config.json`:

- `paper` (current) — simulated fills at last market price into the local ledger.
- `live` — trades are also appended to `data/pending_orders.json`. A Claude
  session with the **robinhood-trading connector** executes them. The connector
  must be authorized first (claude.ai connector settings, or `/mcp` in an
  interactive Claude Code session). Until an order is confirmed executed,
  ledger state in live mode is *intent*, not fact.

## Risk engine

- **Position sizing**: risk-based, not flat-dollar. Shares are sized so that
  hitting the stop loses ~`risk_per_trade_pct` (0.75%) of total equity —
  volatile names with wide stops automatically get smaller positions. Still
  capped by `max_position_usd`.
- **Circuit breakers**: all buying halts (with an email) if equity falls 12%
  from peak or 3% in a day. Exits always keep running.
- **Sector concentration**: max 2 positions per sector.
- **Dilution guard** (EDGAR S-1/S-3/424B): an offering filing in the last 30
  days is a hard veto; 15+ lifetime offering filings marks a chronic diluter
  and counts against confluence.

## Signal learning (bounded, monthly)

Every buy records which signals drove it; every sell pays its P/L back to
those signals (`signal_rewards` table). On the first Sunday of each month,
weights drift ±5% toward what's actually making money — clamped to 50–150%
of the hand-set defaults, minimum 4 closed trades of evidence per signal,
and hard vetoes/risk caps are never touched. Deliberately *not* deep RL:
with dozens of trades a year a neural policy would memorize noise; this is
a slow, auditable bandit. Every adjustment is logged and emailed.

## Safety rails (in config.json — think hard before loosening)

- `price_min: 1.0` — no sub-$1 stocks (delisting risk, manipulation bait)
- `min_avg_dollar_volume: $2M` — avoids illiquid names with punishing spreads
- `max_position_usd: 60` / `max_positions: 6` — caps blast radius per name
- `max_buys_per_week: 1` — prevents churn; also keeps you clear of US
  pattern-day-trader restrictions (accounts under $25k)
- `trailing_stop_pct: 10` / `take_profit_pct: 25` / `max_hold_days: 45`

## Schedule (launchd agents in ~/Library/LaunchAgents)

- `com.josh.tradingbot.research` — 13:37 local, weekdays (weekend-guarded in script)
- `com.josh.tradingbot.scan` — 14:30/16:30/18:30/20:30 local, weekdays

Unlike cron, launchd runs a missed job as soon as the Mac wakes. Manage with:
`launchctl list | grep tradingbot`, or kick one off manually:
`launchctl kickstart gui/501/com.josh.tradingbot.scan`.

For true always-on: keep the laptop plugged in and enable
System Settings → Battery → Options → "Prevent automatic sleeping on power
adapter when the display is off". Optionally add an auto-wake before the
research run: `sudo pmset repeat wakeorpoweron MTWRF 13:30:00`. You must be
logged in (after any reboot, log in once and the agents resume).

## Daily research ("living model")

`research_task.sh` runs a headless Claude session (uses your Claude
subscription) following `research/research_prompt.md`. It web-searches market
regime, sector rotation, catalysts and held-position news, then writes
`data/research.json`, which every scan consumes:

- `market_regime` — risk_on/neutral/risk_off shifts the buy threshold
  (−0.5/+0/+1.0) and all trailing stops (+1/−2 pts)
- `sector_bias` — ±0.5 score adjustment per sector
- `watchlist` — tickers scored as candidates even without insider buys
- `avoid` — blocked from buys; held positions get the tightest stop
- a human-readable journal accumulates in `logs/research_journal.md`

Stale research (>3 days) is ignored; the bot falls back to neutral.

## Email notifications

Every executed buy/sell emails you (with realized P/L on sells), and the
daily research summary is emailed too. **Setup required once**: copy
`data/secrets.example.json` to `data/secrets.json` and paste a Gmail App
Password (create at https://myaccount.google.com/apppasswords — requires 2FA).
Until then, would-be emails are logged to `logs/notify_skipped.log`.

## Adaptive stops (small-to-medium risk)

Per-position trailing stop, clamped 5–12%:
base 10% → 6% on negative news or research red-flag → 12% max on good news
in a risk-on regime. Risk-off tightens everything by 2 pts.

## Signals & scoring

Candidacy is driven by **insider open-market purchases** (Form 4, transaction
code P) ≥ $20k in the last 5 days. Each candidate is then scored:

| signal | source | range × weight |
|---|---|---|
| insider size/clustering | SEC EDGAR | 0–3 × 2.0 |
| sector momentum | SPDR sector ETF 1M/3M returns | 0–1 × 1.0 |
| revenue/earnings growth | Yahoo Finance | 0–2 × 1.5 |
| news sentiment/volume | Yahoo Finance headlines | −2–2 × 1.0 |

A buy needs composite ≥ `min_composite_score` (3.0), available cash, and a
whole share within budget.

## Confluence entry gate

Ranking finds *what* to buy; confluence decides *whether to pull the trigger*.
Before any buy, `bot/signals/technicals.py` checks (config `confluence`):

| check | passes when |
|---|---|
| unusual_volume | time-adjusted relative volume ≥ 1.5× |
| above_vwap | price ≥ today's VWAP (5-min bars) |
| momentum | 5-day return > 0 AND price above 20-day MA |
| tight_spread | bid-ask ≤ 2% |
| price_action | price in upper half of day's range, ≤25% above 20d MA |
| news_ok | news score not negative |
| options_flow | call volume > put volume (skipped if no options) |

Needs ≥4 passes (unknowns don't count against), and four **hard vetoes**
override everything: spread > 3%; ATM implied volatility > 200%; earnings
report within 5 days (binary-event risk); or **Reddit pump risk** — a
parabolic mention spike on a sub-$5 stock with no insider cluster behind it.
Every failed gate is logged with full metrics.

## Reddit signal (ApeWisdom)

Free aggregated mentions across r/wallstreetbets and other investing subs.
Moderate, building buzz adds up to +0.75 to a candidate's score; mentions
exploding >6× in a day *subtract* score, and on cheap stocks trigger the
pump veto above. The bot treats retail hype as confirmation, never as the
thesis.

Options/IV data comes from Yahoo's option chains — free but only exists for
optionable names. When you move to the dedicated PC, drop-in upgrades worth
paying for: Polygon.io (real-time quotes/spreads) or Alpaca (free real-time
IEX feed) — the metrics layer is isolated in `technicals.py` so only that
file needs to change.

## Backtesting

```
python3 backtest.py --months 6          # full run (slow: SEC + price history)
python3 backtest.py --months 6 --tune   # parameter sweep on cached candidates
```

Replays the core insider+momentum engine over historical EDGAR daily indexes
and Yahoo price history: same price/liquidity filters, weekly whole-share
buys from the monthly budget, same stop/take-profit/max-hold exits. Writes
`data/backtest_report.json` + `data/backtest_equity.csv`. A full run caches
its SEC parsing and candidate list, after which `--tune` sweeps 72
stop/take-profit/buys-per-week/score-threshold combinations in minutes and
writes `data/tune_results.json`. Prefer parameter *regions* that perform
consistently over the single best row — the top row is usually luck.

Results are structurally optimistic (close-price fills, no spreads,
survivorship bias, no news/VWAP/IV/Reddit layer) — read the caveats block in
the report.

## Weekly self-review (Sundays 17:03)

`com.josh.tradingbot.review` dumps the week's ledger to
`data/review_input.json`, then a headless Claude session audits every trade
and skipped candidate (including checking what skipped stocks did afterwards),
writes `logs/weekly_review_<date>.md`, and emails it. It may PROPOSE up to
three bounded config changes — it never applies them; you (or a Claude
session you supervise) decide.

## Cloud mode (GitHub Actions + Pages) — one login away

`setup_cloud.sh` deploys everything to GitHub after a one-time `gh auth login`:

- **private repo `trading-bot`** — code + ledger state; GitHub Actions runs
  scans hourly during US market hours (`.github/workflows/scan.yml`), emails
  trades, and commits the ledger back after each run
- **public repo `trading-bot-dashboard`** — GitHub Pages serves the dashboard
  at `https://<user>.github.io/trading-bot-dashboard/`, updated every scan
- email credentials go into Actions **secrets** (never the repo; both
  secrets files are gitignored)
- the script **disables the local scan schedule** so cloud and laptop never
  double-trade; daily research keeps running locally and pushes
  `research.json` to the repo

Caveats: Actions cron can fire a few minutes late (fine); Yahoo sometimes
rate-limits GitHub's shared runners — if scans get flaky, run a self-hosted
runner on the OptiPlex (same workflow, home IP, best of both).

## Moving to a new PC later

Everything is file-based: copy this folder, `pip3 install -r
requirements.txt`, reinstall the two crontab lines (`crontab -l` here to see
them), install Claude Code CLI (`curl -fsSL https://claude.ai/install.sh |
bash`) and log in once. `data/` carries the ledger and secrets with it.

## Honest limitations

- Penny/small-cap stocks are volatile; expect losing trades. The stop-loss
  limits each loss, not the possibility of losses.
- Paper fills use last close, ignoring spread/slippage — real fills on thin
  names will be worse. Treat paper results as optimistic.
- Yahoo Finance data is unofficial and occasionally missing/stale.
- The EDGAR scan reads the ~1,000 most recent Form 4 filings per cycle;
  on very heavy filing days some may be missed (raise `max_pages` in
  `bot/signals/insider.py` if desired).
