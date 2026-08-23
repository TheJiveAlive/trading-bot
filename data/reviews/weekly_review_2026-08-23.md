# Weekly Trading Bot Review — 2026-08-23

**Verdict:** The bot did not trade again this week — the *second consecutive*
week frozen by the same spurious drawdown circuit breaker ("80.6%/80.2% below
peak"), and the recommended fix from last week's review was never applied. This
is no longer just a bug; it is an unactioned bug. Current equity is $136.46
(≈£100, the real T212 demo balance), but the ledger's peak is still the ~$689
artifact from the 7/14 "reset to £500" the broker never held. No closed trade
could produce an 80% loss, and the 6-mo backtest caps drawdown at 17.4%, so the
reading is impossible on its face. The halt short-circuits every candidate
before confluence runs — so the entire system below it is dark. And it was
costly: the slate it blocked rose **+6.4% on average** over the next few days,
including several clean double-digit movers. The outage has now run ~3.5 weeks
(since ~7/29). Fix is operational (reconcile the ledger peak to the live
account), not a config knob — same conclusion as 8/16, now overdue.

## The week in numbers
- Trades: 0 buys, 0 sells, 0 closed round-trips. Win rate: N/A (n=0).
- P/L this week: $0 realized. Open positions: none; 0/20 slots.
- Equity $136.46, 100% cash (broker cash_sync 8/20 adopted $136.46 vs ledger
  $133.74). Demo/fake money; monthly_deposit_usd=0 in the rehearsal, so no real
  deposits to date — the ~£100 practice seed is roughly breakeven.
- Decision log: 6 entries — 5 identical `halt: drawdown circuit breaker` + 1
  cash_sync. Zero confluence/veto skips logged, because the halt runs first.

## What worked
- **Research layer stayed honest under the outage.** It flagged the stale peak
  every single day and refused to carry stale (37-day) risk.json flags without
  live re-verification — good evidence-first hygiene.
- **The insider-misread vetoes it staged were right.** EVLV scored 8.78 (top
  radar, high-conviction tier) but research caught 0 buys / 8 sells and ~$22M
  net insider *selling* — a scoring misread. EVLV then fell −7.9%. ABCL (10.25)
  was correctly benched for a fresh $200M dilution offering; it went ~flat.

## What didn't
- **A ~3.5-week silent outage, and last week's fix was ignored.** The confluence
  gate — the whole point of the system — has not fired in weeks. This is the
  entire story, for the second review running.
- **The halt blocked a strongly positive slate.** Counterfactuals (yfinance,
  8/14→8/21 common base): SENS +24.3%, BTDR +24.5%, SUJA +18.5%, QTRX +15.4%,
  BFLY +8.0%, BORR +1.6%, NRGV +0.3%; ABCL −0.5%, ANGX −1.4%, PAL −3.1%,
  SGRY −3.4%, EVLV −7.9%. Mean **+6.4%** (12 names); the two losers the research
  layer would have vetoed anyway (EVLV misread, ABCL dilution). A clean miss on
  a risk_on tape while frozen.
- **No trade-quality or stop evidence exists this week.** Nothing held, exited,
  or stopped — signal weights, stop width, and score thresholds are all untested
  by the week's data. There is nothing to tune from zero fills.

## Proposed config changes
**No config changes warranted.** The failure is operational, not a mis-set
parameter. `drawdown_halt_pct` (12.0) is a hard safety rail behaving *correctly*
against a corrupted input — touching it would only mask the bug and is off-limits
regardless. The required action, out of scope for config.json and now overdue:
**reset the ledger's peak-equity high-water mark to the live demo balance
(~$136)** so the breaker measures real losses again. Until that happens, every
weekly review will say exactly this. Do it, confirm the book is genuinely flat,
and let real fills accumulate before anyone touches a weight, stop, or threshold.
