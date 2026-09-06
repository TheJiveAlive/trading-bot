# Weekly review — 2026-09-06

## Verdict
The bot did not trade this week, and it could not have: every scan hit the
drawdown circuit breaker reading "80.2% below peak (limit 12.0%)". That number
is a bookkeeping artifact, not a real loss. Peak equity of $689.18 was written
on 2026-07-15 during the brief £500 demo top-up; the demo account was later
reset to £100 (~$136.46) and the ledger adopted that cash, but the equity
high-water mark was never reset. The breaker has therefore compared live
~$136 against a phantom $689 peak and force-halted all buying since ~2026-07-29
— the last actual trade was 2026-07-22. No capital was lost (the backtest engine
returns +13.3% over 6 months); the bot is simply bricked. The research/avoid
layer, meanwhile, did excellent work all week and is being wasted behind a dead
gate. This is an operational fix, not a tuning problem.

## The week in numbers
- Trades: 0 buys, 0 sells. Open positions: 0 (book flat since 2026-07-22).
- Decisions logged: 4, all `halt` on the same stale-peak drawdown breaker.
- P/L this week: $0. Win rate: n/a (no closed trades).
- Equity $136.46 vs demo funding ~£100 (~$136) — intact/flat. The $689.18
  "peak" is a 7/14 demo-reset artifact, not earned-then-lost capital.
- Long-run evidence (backtest 2026-03-04→08-31): +13.3% vs SPY +12.6%,
  53 trades, 54.7% win rate, max DD 14.2%.

## What worked
- The avoid/confluence layer is well-calibrated. Counterfactuals (28 Aug→5 Sep)
  on the top skipped names it flagged as dilution/fraud/artifact misreads:
  RGNX −7.5%, TENX −8.9%, BATL −1.5%, IMTX +1.2% (flat) — skips correct.
  SUJA +12.2% is the one that got away, but on a broken IPO (−70%) with active
  fraud probes; avoiding it is sound risk discipline, not miscalibration.
- The one clean buyable it identified and wanted, NPB (fresh CEO open-market
  buys, radar ~9.0), did +1.4% — a modest win the halt denied it.

## What didn't
- The drawdown breaker is a permanent false positive. It blocks every candidate
  before confluence even runs, so no genuine skip decisions were made this week
  and a legitimate NPB entry was suppressed. The journal has flagged this daily
  since ~7/29; it remains unfixed.
- `force_regime: risk_on` contradicted the research layer's risk-off/neutral
  read every single day this week (Iran/Hormuz oil shock, hot 9/4 jobs, Sept
  rate-hike odds, small-cap-hostile tape). Moot while halted, but stale.

## Proposed config changes
None warranted — no parameter change is the right fix, and widening
`drawdown_halt_pct` to mask this would disable a real safety guard.

The required fix is OPERATIONAL, not config: reset the ledger equity
high-water mark from $689.18 to live equity (~$136.46) so the breaker measures
real drawdown. Until then the bot cannot trade regardless of any tuning.

Optional, once unhalted (evidence: research called risk-off/neutral all week):
- `force_regime: risk_on -> null` — restore the adaptive conservative blend the
  tape actually supported; hard vetoes and confluence are unaffected.
