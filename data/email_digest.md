
### 15:57 UTC · [test] routine
should buffer

### 15:59 UTC · [bot boxwatch] 0 self-healed, 2 open
## Boxwatch report — 15:59 UTC
- **OPEN**: intel.json — 115m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 99m stale (agent dispatch chain may be broken)

**Local triage** (high): Two independent outputs — intel.json (115m) and risk.json (99m) — went stale within ~15 minutes of each other, and neither producer logged a warning to the journal. Files that stop updating together with zero error output almost never means two separate scripts crashed simultaneously; it points to a shared upstream: the agent dispatch/scheduler that fans work out to these producers is not firing (dead cron/systemd timer, hung dispatcher process, or a killed parent), so the child jobs never run and therefore never log. The ~100m age with no self-heal means the local watchdog's remediation (restart/re-dispatch) either isn't wired to this chain or is itself blocked. On a live trading host during market hours, a stale risk.json means risk limits are being evaluated against data over an hour and a half old.

Suggested commands:
- `systemctl --no-pager status '*dispatch*' '*agent*'; systemctl list-timers --all | grep -iE 'intel|risk|dispatch'`
- `ps -ef | grep -iE 'dispatch|agent|intel|risk

### 16:21 UTC · 🔴 SELL UUUU — 6.1781 shares @ $12.50  ·  P/L −$6.30 (-7.5%)
SELL UUUU x6.1781 @ $12.50 ($77.23)
P/L: -$6.30 (-7.5%)
why: insider selling — Form 144 proposed insider sale $5596k — bearish tell, exiting
cash: $368.61
equity: $677.59

### 17:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 17:53 UTC
- **OPEN**: risk.json — 92m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 18:03 UTC
- **OPEN**: risk.json — 102m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:13 UTC · [bot boxwatch] 0 self-healed, 2 open
## Boxwatch report — 18:13 UTC
- **OPEN**: intel.json — 100m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 112m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:23 UTC · [bot boxwatch] 0 self-healed, 2 open
## Boxwatch report — 18:23 UTC
- **OPEN**: intel.json — 110m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 122m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:33 UTC · [bot boxwatch] 0 self-healed, 2 open
## Boxwatch report — 18:33 UTC
- **OPEN**: intel.json — 120m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 132m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:39 UTC · 🔴 SELL NTSK — 6.4097 shares @ $13.37  ·  P/L +$2.12 (+2.5%)
SELL NTSK x6.4097 @ $13.37 ($85.67)
P/L: +$2.12 (+2.5%)
why: trailing stop (11%): 10.7% off high
cash: $454.28
equity: $670.45

### 18:43 UTC · [bot boxwatch] 0 self-healed, 2 open
## Boxwatch report — 18:43 UTC
- **OPEN**: intel.json — 130m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 142m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:44 UTC · 🟢 BUY NTSK — 7.0931 shares @ $13.25
BUY NTSK x7.0931 @ $13.25 ($93.99)
why: score 9.62 (parts {'insider': 6.0, 'sector': 0.8, 'fundamentals': 1.5, 'news': 0.0, 'piotroski': 0.25, 'ai_news': 0.5, 'insider_sentiment': -0.06, 'analyst_trend': 0.38, 'events': 0.4, 'sector_bias': -0.15}); risk-sized 7.0931 sh at 11% stop; confluence: 8/10 pass | unusual_volume | momentum | tight_spread | news_ok | options_flow | rsi_ok | clean_dilution_history | no_insider_selling | FAIL: above_vwap,price_action; critic unavailable (Expecting value: line 1 column 1 (char 0)) — fail-open
cash: $360.29
equity: $670.47

### 18:53 UTC · [bot boxwatch] 0 self-healed, 2 open
## Boxwatch report — 18:53 UTC
- **OPEN**: intel.json — 140m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 152m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 06:35 UTC · [goldbot research] 2026-07-15 regime: corrective consolidation below ATH; elevated real yields cap rallies while Hormuz-oil inflation fears give a two-sided safe-haven squeeze
{
  "date": "2026-07-15",
  "regime": "corrective consolidation below ATH; elevated real yields cap rallies while Hormuz-oil inflation fears give a two-sided safe-haven squeeze",
  "bias_check": "agree \u2014 the bot's -1 (bearish) read is well-supported: 10Y real yields have climbed to ~2.36% (+0.20 over two weeks), COT specs are crowded long (52% of OI), TradingView reads sell (-0.45) and analysts frame it as sell-on-rise; the cross-feed adds nothing today (tilt 0, 'rh gold regime: chop'); the only caveat is that Hormuz safe-haven bids and the soft-CPI bounce can squeeze shorts (today's short was stopped for -$13).",
  "key_levels": {
    "support": [
      4000,
      3960,
      3887
    ],
    "resistance": [
      4081,
      4112,
      4300
    ]
  },
  "events_next_48h": [
    "Fed Chair Kevin Warsh Senate Banking Committee testimony today ~10:00 ET / 15:00 UK (high-impact USD; bot's event blackout gate active)",
    "US-Iran strikes / Strait of Hormuz naval blockade \u2014 unscheduled oil-spike headline risk, two-sided for gold (safe-haven bid vs higher-for-longer rate fears)",
    "US weekly jobless claims Thu Jul 16 (minor); note the next FOMC is Jul 28\u201329, outside

### 06:43 UTC · [bot boxwatch] 1 self-healed, 0 open
## Boxwatch report — 06:43 UTC
- **self-healed**: git repo (repaired: empties deleted, refetched, reset to origin/main)

### 06:53 UTC · [bot boxwatch] 1 self-healed, 0 open
## Boxwatch report — 06:53 UTC
- **self-healed**: lan-dashboard.service (restarted (1/3))

### 07:04 UTC · [bot boxwatch] 1 self-healed, 0 open
## Boxwatch report — 07:03 UTC
- **self-healed**: lan-dashboard.service (restarted (2/3))

### 07:13 UTC · [bot boxwatch] 1 self-healed, 0 open
## Boxwatch report — 07:13 UTC
- **self-healed**: lan-dashboard.service (restarted (3/3))

### 07:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 07:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 07:43 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 07:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 07:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 07:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 08:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 08:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 08:13 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 08:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 08:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 08:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 08:33 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 08:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 08:43 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 08:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 08:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 08:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 09:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 09:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 09:13 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 09:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 09:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 09:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 09:33 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 09:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 09:43 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 09:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 09:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 09:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 10:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 10:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 10:13 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 10:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 10:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 10:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 10:33 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 10:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 10:43 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 10:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 10:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 10:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 11:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 11:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 11:13 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 11:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 11:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 11:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 11:33 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 11:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 11:43 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 11:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 11:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 11:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 12:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 12:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 12:13 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 12:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 12:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 12:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 12:33 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 12:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 12:43 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 12:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 12:52 UTC · [goldbot research] 2026-07-15 regime: corrective consolidation below ATH; elevated real yields cap rallies while Hormuz-oil inflation fears give a two-sided safe-haven squeeze
{
  "date": "2026-07-15",
  "regime": "corrective consolidation below ATH; elevated real yields cap rallies while Hormuz-oil inflation fears give a two-sided safe-haven squeeze",
  "bias_check": "agree \u2014 the bot's -1 (bearish) read is well-supported: 10Y real yields have climbed to ~2.36% (+0.20 over two weeks), COT specs are crowded long (52% of OI), TradingView reads sell (-0.45) and analysts frame it as sell-on-rise; the cross-feed adds nothing today (tilt 0, 'rh gold regime: chop'); the only caveat is that Hormuz safe-haven bids and the soft-CPI bounce can squeeze shorts (today's short was stopped for -$13).",
  "key_levels": {
    "support": [
      4000,
      3960,
      3887
    ],
    "resistance": [
      4081,
      4112,
      4300
    ]
  },
  "events_next_48h": [
    "Fed Chair Kevin Warsh Senate Banking Committee testimony today ~10:00 ET / 15:00 UK (high-impact USD; bot's event blackout gate active)",
    "US-Iran strikes / Strait of Hormuz naval blockade \u2014 unscheduled oil-spike headline risk, two-sided for gold (safe-haven bid vs higher-for-longer rate fears)",
    "US weekly jobless claims Thu Jul 16 (minor); note the next FOMC is Jul 28\u201329, outside

### 12:53 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 12:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 13:03 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 13:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 13:13 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 13:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 13:23 UTC · [bot boxwatch] 0 self-healed, 1 open
## Boxwatch report — 13:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)

Sandboxed medic dispatched (unless on cooldown).

### 13:30 UTC · 🔴 SELL NTSK — 7.0931 shares @ $13.21  ·  P/L −$0.33 (-0.3%)
SELL NTSK x7.0931 @ $13.21 ($93.66)
P/L: -$0.33 (-0.3%)
why: insider selling — Form 144 proposed insider sale $2775k — bearish tell, exiting
cash: $453.95
equity: $665.71

### 13:33 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 13:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2700m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2712m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 13:43 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 13:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2710m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2722m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 13:53 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 13:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2720m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2732m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 14:03 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 14:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2730m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2742m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 14:13 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 14:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2740m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2752m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 14:23 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 14:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2750m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2762m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 14:33 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 14:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2760m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2772m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 14:43 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 14:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2770m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2782m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 14:53 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 14:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2780m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2792m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 15:03 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 15:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2790m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2802m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 15:13 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 15:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2800m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2812m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 15:23 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 15:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2810m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2822m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 15:33 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 15:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2820m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2832m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 15:43 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 15:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2830m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2842m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 15:53 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 15:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2840m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2852m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 16:03 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 16:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2850m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2862m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 16:13 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 16:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2860m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2872m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 16:23 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 16:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2870m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2882m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 16:33 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 16:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2880m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2892m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 16:43 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 16:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2890m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2902m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 16:53 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 16:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2900m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2912m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 17:03 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 17:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2910m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2922m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 17:13 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 17:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2920m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2932m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 17:23 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 17:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2930m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2942m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 17:33 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 17:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2940m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2952m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 17:43 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 17:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2950m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2962m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 17:53 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 17:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2960m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2972m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:03 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 18:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2970m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2982m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:13 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 18:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2980m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 2992m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:23 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 18:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 2990m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3002m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:33 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 18:33 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 3000m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3012m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:43 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 18:43 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 3010m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3022m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 18:53 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 18:53 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 3020m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3032m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 19:03 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 19:03 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 3030m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3042m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 19:13 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 19:13 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 3040m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3052m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).

### 19:23 UTC · [bot boxwatch] 0 self-healed, 3 open
## Boxwatch report — 19:23 UTC
- **OPEN**: lan-dashboard.service — activating (restart budget exhausted — needs medic)
- **OPEN**: intel.json — 3050m stale (agent dispatch chain may be broken)
- **OPEN**: risk.json — 3062m stale (agent dispatch chain may be broken)

Sandboxed medic dispatched (unless on cooldown).
