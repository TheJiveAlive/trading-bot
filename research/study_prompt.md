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
5a. `data/screens.json` (if present) — the box's NIGHT-SHIFT screens over the
   full 7,700-ticker universe: RVOL, 52-week-high proximity, 13-week
   cross-sectional momentum rank. Use it to VALIDATE the strategy-gap backlog
   items with real distributions (e.g. do our winners come from high-RVOL
   names?) before proposing any of them as score inputs.
5. `data/data_quality.json` (if present) — the NIGHTLY DATA-TRUST AUDIT:
   bars.db vs fresh Yahoo closes, staleness, flat-lined series, and T212's
   live price vs our cache (broker = account of record, it wins disputes).
   YOU are the judge this audit reports to: for each flagged ticker decide
   whether its data can be trusted, say so in learnings.md, and if a HELD
   ticker's sources disagree, say it LOUDLY. Many mismatches on a ticker =
   distrust its backtest rows too.
6b. `backtest_report.json` now carries `survivorship_exposure` — the % of
   insider-active tickers that can no longer be priced (likely delisted).
   Treat every backtest return as an UPPER BOUND by roughly that order of
   magnitude until survivorship-free data is bought.
5c. `data/finbert.json` (if present) — LOCAL transformer sentiment (FinBERT
   on the box, deterministic, per-headline). VALIDATE before it earns score
   weight: do tickers with strongly positive mean sentiment at entry win more
   often? Compare against the existing news_score — if FinBERT adds nothing
   over it, say so and we keep it display-only.
5d. `data/quant_regime.json` (if present) — UNSUPERVISED K-means market state
   (calm_drift / trending / stress) from SPY price action. Cross-check it
   against research.json's regime call: when they DISAGREE, investigate which
   was right in hindsight and log the verdict — this decides whether the
   quant state should join the dynamic-caps blend.
5e. `data/lorentzian.json` (if present) — nightly Lorentzian k-NN
   classification over the full pond (the TradingView-famous method: k
   nearest historical days by Lorentzian distance vote on the 4-session
   forward direction). VALIDATE: do high-score names actually drift up over
   the next week? Track a paper cohort in learnings.md before proposing it
   as a score input or confluence check.
5f. `data/local_digest.json` — the local-LLM filing/news pre-screen. Spot-check its dilution_risk/going_concern calls against reality on a few names: is the local model reliable enough to pre-filter, or does it hallucinate? Log the verdict.
6. `walkforward.json` now carries `risk_metrics_top_combo` (Sharpe, Sortino,
   profit factor, expectancy, and a 1000x Monte Carlo bootstrap of the trade
   sequence). A negative Monte Carlo p5 means the edge may hinge on a few
   lucky trades — weight your conclusions accordingly.

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
   - **Share-structure screen**: float size, shares outstanding growth
     (serial diluter fingerprint), warrant overhang. Free via yfinance +
     EDGAR filing counts. The risk officer agent checks live filings; this
     item is the SCREENING version (score it before we ever buy).
   - **Vol-target sizing**: scale position size inversely to the name's
     20-day realized volatility (vol from the bar cache) instead of a flat
     risk %. Keeps risk-per-trade constant across calm and wild names.
   - **Congress-trades copycat**: free public periodic transaction reports
     (Senate/House disclosure feeds, e.g. Senate Stock Watcher JSON). Same
     DNA as our Form-4 engine; caveat the 45-day disclosure lag — test
     whether any drift survives it for small caps.
   - **Factor ranks (Carhart-lite)**: rank candidates on size/value/momentum
     percentiles from yfinance fundamentals + the bar cache, as a tilt not a
     strategy. Validate against outcomes before it earns weight.
   - **10-K/10-Q risk-factor mining**: EDGAR full text is free — candidate's
     latest filing's risk-factors/going-concern language as a Claude read
     during research. Complements the risk officer's filing checks.
   When an item has been studied, record the verdict in learnings.md so later
   sessions move to the NEXT item instead of repeating it.
7. **Forum mining** (each session, ~5 min): search practitioner sources for
   tactics relevant to a $1–20 catalyst/insider small-cap bot — r/algotrading,
   r/pennystocks lessons threads, EliteTrader, QuantConnect forum, Quantpedia
   blog. You are looking for CONCRETE, testable rules (entry filters, exit
   structures, sizing tricks, red flags), not vibes. If you find one we don't
   have, add it to the strategy-gap backlog verdicts in learnings.md with the
   source. If a forum insight CONTRADICTS something we do (e.g. our TP/stop
   structure), surface the disagreement honestly.

8. **URGENT — exit-window conflict (2026-07-14)**: the 6-month sweep and the
   8-week OOS test favour stop 8/TP 15, but the full 12-month sim LOSES 11.5%
   with those exits vs +23.5% at stop 15/TP 25. Exits are held at 12/25 and
   auto-tune is PAUSED pending your adjudication: which window reflects the
   regime we trade in NOW, and should tune rank across both windows (e.g.
   worst-case-of-windows) before it may touch live exits again?

## Write
Append a dated section to `data/learnings.md` (create if missing):
- **Date & headline** (one line)
- **What the data says** (3-5 bullet points, specific)
- **Proposed change** (one, bounded — parameter/signal, with the thesis)
- Do NOT edit config.json or code. You PROPOSE; the human decides.

Keep it under 40 lines. Evidence over speculation. If the data is too thin to
conclude anything (few trades), say so honestly rather than inventing signal.
