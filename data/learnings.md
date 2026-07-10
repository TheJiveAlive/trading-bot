# Learnings

## 2026-07-10 — Overtrading looks like the bigger lever than stop/TP tuning

**What the data says:**
- Backtest (Jan 8–Jul 7, 35 closed trades): -18.2% vs SPY +9.0%. Win rate 40%, avg win +10.2%, avg loss -9.9%. At that win rate a ~1:1 payoff is a losing expectancy (~-1.9%/trade) — the edge problem is win rate, not payoff skew.
- Exit mix is lopsided: 25/35 trades (71%) hit the trailing stop (sum -143.1pp), only 3/35 (9%) reached the 25% take-profit (sum +86.5pp), and 7/35 (20%) rode to max_hold (45d) averaging -1.2% — dead money that neither worked nor got cut.
- Tune sweep confirms the *current* stop/TP (8%/25%) sits in the most robust region tested: avg return -0.7%, worst-case -2.6% across min_score variants — far better worst-case than e.g. 12%/15% (worst -18.6%) or 15%/20% (worst -14.6%). So stop/TP are not the prime suspect.
- Strongest pattern in the sweep: for every single stop/TP pair tested, buys_wk=2 underperformed buys_wk=1 by 2-4pp (e.g. 8%/25%: +1.3% at 1 buy/wk vs -2.6% at 2 buys/wk). More trades per week made results worse in 100% of tested combos.
- Caveat: live config's `max_buys_per_week` is 20 — the sweep only ever tested 1-2/week, so the actual live cap has never been validated by tuning. Live decision feed is too thin right now (14 decisions, fresh paper reset) to say which confluence check rejects the most candidates — 6/8 skip_buys failed on `unusual_volume`, but n=8 is not enough to act on alone.

**Proposed change:** Lower `buying.max_buys_per_week` from 20 down to something inside the validated range (e.g. 4) as a bounded test. Thesis: every stop/TP combination in the tune sweep got worse when trade frequency doubled from 1 to 2/week, and the live cap of 20 is far outside anything the tuning process has actually confirmed. Forcing more selectivity per week should concentrate capital in the highest-score/highest-confluence setups rather than filling the book, which may lift the 40% win rate toward the ~45-50% needed for the current payoff ratio to be profitable. Re-run the tune sweep with buys_wk values up to 5-6 to extend the validated range before committing further.
