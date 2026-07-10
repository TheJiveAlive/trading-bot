# Learnings

## 2026-07-10 — Overtrading looks like the bigger lever than stop/TP tuning

**What the data says:**
- Backtest (Jan 8–Jul 7, 35 closed trades): -18.2% vs SPY +9.0%. Win rate 40%, avg win +10.2%, avg loss -9.9%. At that win rate a ~1:1 payoff is a losing expectancy (~-1.9%/trade) — the edge problem is win rate, not payoff skew.
- Exit mix is lopsided: 25/35 trades (71%) hit the trailing stop (sum -143.1pp), only 3/35 (9%) reached the 25% take-profit (sum +86.5pp), and 7/35 (20%) rode to max_hold (45d) averaging -1.2% — dead money that neither worked nor got cut.
- Tune sweep confirms the *current* stop/TP (8%/25%) sits in the most robust region tested: avg return -0.7%, worst-case -2.6% across min_score variants — far better worst-case than e.g. 12%/15% (worst -18.6%) or 15%/20% (worst -14.6%). So stop/TP are not the prime suspect.
- Strongest pattern in the sweep: for every single stop/TP pair tested, buys_wk=2 underperformed buys_wk=1 by 2-4pp (e.g. 8%/25%: +1.3% at 1 buy/wk vs -2.6% at 2 buys/wk). More trades per week made results worse in 100% of tested combos.
- Caveat: live config's `max_buys_per_week` is 20 — the sweep only ever tested 1-2/week, so the actual live cap has never been validated by tuning. Live decision feed is too thin right now (14 decisions, fresh paper reset) to say which confluence check rejects the most candidates — 6/8 skip_buys failed on `unusual_volume`, but n=8 is not enough to act on alone.

**Proposed change:** Lower `buying.max_buys_per_week` from 20 down to something inside the validated range (e.g. 4) as a bounded test. Thesis: every stop/TP combination in the tune sweep got worse when trade frequency doubled from 1 to 2/week, and the live cap of 20 is far outside anything the tuning process has actually confirmed. Forcing more selectivity per week should concentrate capital in the highest-score/highest-confluence setups rather than filling the book, which may lift the 40% win rate toward the ~45-50% needed for the current payoff ratio to be profitable. Re-run the tune sweep with buys_wk values up to 5-6 to extend the validated range before committing further.

## 2026-07-10 (later) — min_composite_score barely filters anything; insider is nearly the whole score

**What the data says:**
- In `tune_results.json`, 31 of 40 (stop, tp, buys_wk) buckets return byte-identical trades/win-rate/return whether `min_score` is 2.5, 3.0, or 4.0 — raising the threshold 60% removes zero candidates in most regions. The 9 buckets where it does matter are almost all in already-poor stop/tp regions (12%/15-30% stops), not near the current config.
- Every one of the 26 live `scan_candidates` rows this week has `insider` as by far the largest score component (2.0–5.0 of a 2.9–6.8 total); `sector` adds a small amount (0–0.9); `fundamentals`/`news`/`breakout` are nonzero in only 3, 2, and 2 rows respectively; `reddit` and `events` never appear at all despite carrying configured weights (0.75, 1.0).
- Mechanically this checks out: `insider_score()` (bot/signals/insider.py) is capped at raw 3.0 (×`insider_weight` 2.0 = 6.0 max), and a single insider buying ≥$250k alone already scores 2.5 raw → 5.0 — above the current `min_composite_score` of 2.5 with no help from any other signal. AVO and VII-UN both hit the 5.0 insider-only ceiling this week.
- Net effect: the composite score, as actually populated, is functioning close to "insider hit or not" rather than a true multi-signal confluence score — `min_composite_score` at 2.5 (or even 4.0) doesn't force any corroboration from sector/fundamentals/news/breakout.
- Caveat: sample is thin (26 candidates from 3 scan runs, only 2 closed... 0 closed live trades) — can't yet say whether reddit/events being silent is a real "quiet week" or a pipeline gap; `signal_rewards` is empty (0 rows) simply because no live paper position has closed yet since the 7/7 reset, so the learning loop's "no adjustments" today is expected, not a bug.

**Proposed change:** Raise `buying.min_composite_score` from 2.5 to ~5.5 as a bounded test — above the single-insider-only ceiling of 5.0, so a candidate must get corroboration from at least one other signal (sector/fundamentals/news/breakout) to qualify, not insider alone. Thesis: this directly targets the "insider is nearly the whole score" pattern above without touching any individual signal weight. Re-run the tune sweep with finer min_score steps (4.5, 5.0, 5.5, 6.0) to find where the threshold actually starts cutting trades, since 2.5→4.0 barely moved anything.
