# Weekly Trading Bot Review — 2026-08-16

**Verdict:** The bot did not trade at all this week, and that is a bug, not
discipline. Every scan from 8/10–8/13 hit the same wall — a drawdown circuit
breaker reading "80.6% below peak" — and halted before confluence was ever
evaluated. That 80.6% is a bookkeeping artifact: current equity is $133.74
(≈£100, the real T212 demo balance), but the ledger's peak is ~$689 — the
$670 figure seeded at the 7/14 "reset to £500" that the broker never actually
held. There are zero closing trades that could produce such a loss, and the
6-month backtest maxes out at 17.4% drawdown, so an 80% real drawdown is
implausible. The research layer flagged this as a stale peak five days running
and asked a human to confirm. It was right, and it silently cost money: the
slate it blocked rose ~+2.4% on average over the next few days. Fix is
operational (reconcile the ledger peak to the live account), not a config knob.

## The week in numbers
- Trades: 0 buys, 0 sells, 0 closed round-trips. Win rate: N/A (n=0).
- P/L this week: $0 realized (no fills). Open positions: none.
- Equity $133.74, 100% cash, 0/20 slots used. Demo account (fake money);
  monthly_deposit_usd=0 during the rehearsal, so no real deposits to date.
- Decision log: 9 scans this week, all identical — `halt: drawdown circuit
  breaker 80.6% below peak (limit 12.0%)`. No confluence/veto skips logged,
  because the halt short-circuits every candidate before the gate runs.

## What worked
- **The research layer correctly diagnosed the halt** as a spurious stale peak
  and refused to trust stale risk.json flags — good evidence-first hygiene.
- **The one veto call that mattered was right:** OPFI (radar 4.75, flagged as
  an insider misread — 5 sales/0 buys into an 8/10 Q2 miss) fell −18.4%. Had
  the halt not blocked everything, that judgment would still have saved a loss.

## What didn't
- **A ~2.5-week silent outage (since ~7/29).** The confluence gate, the whole
  point of the system, never fired once. This is the entire story of the week.
- **The halt blocked a net-positive slate.** Counterfactuals (yfinance, entry
  date → 8/16): AHCO (top score 10.75) +11.3%, PTLO +15.2%, CC +9.3%, BTDR
  +5.0%, LTGO +5.0%, BV +4.1%, ABTC +2.7%, EMBC +2.2%, VISN +1.0%; SUJA −1.2%,
  ALTO −1.2%, NATR −4.1%, OPFI −18.4%. Mean +2.4% (all 13), +4.1% excluding the
  correctly-flagged OPFI. The bot missed a decent risk_on tape by staying frozen.
- **No trade-quality or stop evidence exists this week** — nothing was held or
  exited, so signal weights, stop width, and thresholds are all untested by
  the week's data. Nothing to tune from zero fills.

## Proposed config changes
**No config changes warranted.** The failure is operational, not a mis-set
parameter. `drawdown_halt_pct` (12.0) is a hard safety rail behaving correctly
against a corrupted input — lowering or raising it would only mask the real
bug. The needed fix is out of scope for this review and for config.json:
**reset the ledger's peak-equity high-water mark to the actual live demo
balance (~$134)** so the drawdown breaker measures real losses again. Do that,
confirm the account is genuinely flat, and let next week produce real fills
before touching any signal weight, stop, or score threshold.
