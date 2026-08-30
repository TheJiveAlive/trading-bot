# Weekly Trading Bot Review — 2026-08-30

**Verdict:** Same wall, third week running. Every scan (8/24, 8/25, 8/26, 8/28)
halted on a drawdown circuit breaker reading "80.2% below peak" before confluence
ever ran, so the entire system below the breaker stayed dark for a fourth
consecutive week (~4.5 weeks since ~7/29). The 80.2% is a bookkeeping artifact,
not a real loss: the T212 demo account is reachable and flat at **£100 / 0
positions** (broker_state.json), ledger cash is $136.46, but the ledger's peak
high-water mark is still the ~$689 figure seeded at the 7/14 "reset to £500" the
broker never actually held. No closed trade can produce an 80% drawdown, and the
6-mo backtest caps at 17.4%. The fix was recommended on 8/16 and 8/23 and remains
unapplied — this is now an unactioned operational bug, not a config problem. The
one twist this week: the blocked slate actually *underperformed* (mean −3.6% on
the names with a follow-through window), so the freeze was accidentally
protective. That is luck, not judgment — the gate reasoned about nothing.

## The week in numbers
- Trades: 0 buys, 0 sells, 0 closed round-trips. Win rate: N/A (n=0).
- P/L this week: $0 realized. Positions: none; 0/20 slots.
- Equity $136.46, 100% cash. Real deposits to date: £0 beyond the £100 demo seed
  (monthly_deposit_usd=0 in the rehearsal) — the account is roughly breakeven.
- Decision log: 4 entries, all identical `halt: drawdown circuit breaker`. Zero
  confluence/veto skips logged, because the halt short-circuits everything first.

## What worked
- **The safety rail is behaving correctly against a bad input.** A 12% drawdown
  halt firing on a reported 80% loss is the breaker doing its job; the fault is
  the corrupted peak feeding it, not the threshold.
- **Being frozen didn't cost money this week.** Counterfactuals (yfinance, decided
  8/24–8/26 → 8/28 close): SUJA +3.5%, NWBI −0.2%, SENS −0.5%, SGRY −1.9%,
  KURA −3.1%, ABCL −7.3%, TENX −8.2%, DXST −10.8% — mean **−3.6%**. Unlike the
  +6.4% and +2.4% slates the prior two reviews watched slip away, this one fell.

## What didn't
- **A ~4.5-week silent outage, fix ignored twice.** The confluence gate — the
  point of the whole system — has not fired in over a month. This is the entire
  story, for the third review in a row.
- **Zero trade-quality, stop, or thesis evidence exists.** Nothing was held,
  exited, or stopped. Signal weights, stop width, and score thresholds are all
  untested by the week's data. There is nothing to tune from zero fills, and no
  single-position loss to assess against the 12% risk expectation.
- **The 8/28 slate (KLAR, IMTX, RGNX, NPB, NOMD, HDSN, CHY) can't be judged** —
  decided on the last trading day, no follow-through window yet.

## Proposed config changes
**No config changes warranted.** The failure is operational, not a mis-set
parameter, and `drawdown_halt_pct` (12.0) is a hard safety rail off-limits by the
review rules — touching it would only mask the bug. The required action, out of
scope for config.json and now well overdue: **reset the ledger's peak-equity
high-water mark to the live demo balance (~$136)** so the breaker measures real
losses again. Until that is done, confirm the book is genuinely flat, and let
real fills accumulate, every weekly review will keep saying exactly this.
