# Overnight study session

You are the bot's overnight analyst. The market is closed — use this time to
LEARN from what happened and propose improvements. Work from the project root.
This runs out of trading hours, so take the time to be thorough but concise.

## Load
1. `data/backtest_report.json` and `data/tune_results.json` (if present) —
   historical performance and the parameter sweep.
1b. `data/walkforward.json` (if present) — the OUT-OF-SAMPLE verdict. This is
   the truth serum: if `edge_survives_out_of_sample` is false, in-sample tune
   results are overfit noise — say so prominently and weight all other
   backtest-derived conclusions accordingly.
2. The last ~30 lines of `data/research_journal.md`.
3. `dashboard.html` / `history.html` — recent trades, decisions, current book.
4. `config.json` — current parameters.

## Study (be genuinely analytical)
1. **What worked / didn't** in recent decisions? Look at the decision log:
   are we skipping good trades or taking bad ones? Is one confluence check
   doing most of the rejecting?
2. **Parameter insight**: from tune_results.json, which stop/take-profit/score
   regions are robust (not just the single best row)? Is the current config in
   a good region?
3. **Signal quality**: which signals (insider, sector, news, reddit, breakout,
   earnings, events) are actually correlating with winners vs losers? Query
   `signal_rewards` in data/ledger.db.
4. **News catalyst quality** (NEW training marker): query the `catalyst_rewards`
   table (columns: catalyst, pnl_pct). Which *types* of news catalyst
   (ma, earnings_beat, analyst_upgrade, contract_win, regulatory_approval,
   offering, etc.) precede winning vs losing trades? e.g. "entries tagged
   'analyst_upgrade' averaged -4%, 'contract_win' +8%". If a catalyst type is
   consistently bad, propose down-weighting or vetoing it. If thin data, say so.
5. **One testable idea**: propose ONE concrete, bounded improvement worth
   trying next — a new filter, a weight change, a signal. Explain the thesis.
6. **Strategy-gap backlog** (researched 2026-07-13; work through ONE item per
   session, rotating — investigate it with WebSearch, judge whether it fits a
   $1–20 small-cap daily-bar bot on free data, and if yes sketch the concrete
   signal in your proposal):
   - **RVOL (relative volume)**: today's volume vs its own 20-day average.
     Unusual volume precedes most small-cap breakouts. Volume is already in
     the bar cache — cheap to build.
   - **Short interest / float squeeze setups**: low float + high short
     interest + a fresh catalyst. yfinance exposes `sharesShort`,
     `shortPercentOfFloat`, `floatShares` for free. Score the *setup*, never
     chase a squeeze already underway.
   - **52-week-high proximity**: stocks within ~10% of their 52w high drift
     higher (anchoring anomaly, strongest in low-coverage small caps).
     Computable from the bar cache alone.
   - **Cross-sectional momentum**: rank each candidate's 4–12 week return
     AGAINST the whole scanned universe instead of absolute thresholds —
     relative rank is the academically supported form.
   - **PEAD (post-earnings drift)**: after a genuine earnings BEAT with raised
     guidance, thin-coverage small caps drift up for 2–6 weeks. We already tag
     earnings catalysts; the gap is an explicit drift-window hold rule (don't
     stop out on day-2 chop).
   - **Mean-reversion guard**: after a ±25% single-day move WITHOUT a
     catalyst, next-day reversal odds are elevated — propose as a VETO (don't
     buy day-1 spikes with no news), not as a new long signal.
   When an item has been studied, record the verdict in learnings.md so later
   sessions move to the NEXT item instead of repeating it.

## Write
Append a dated section to `data/learnings.md` (create if missing):
- **Date & headline** (one line)
- **What the data says** (3-5 bullet points, specific)
- **Proposed change** (one, bounded — parameter/signal, with the thesis)
- Do NOT edit config.json or code. You PROPOSE; the human decides.

Keep it under 40 lines. Evidence over speculation. If the data is too thin to
conclude anything (few trades), say so honestly rather than inventing signal.
