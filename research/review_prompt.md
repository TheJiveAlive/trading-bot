# Weekly trading bot self-review

You are reviewing a week of an automated small-cap trading bot's behavior.
Work from the project root (/Users/josh/Desktop/RobinHood). Your goal is an
honest performance review with concrete, bounded tuning proposals — you
PROPOSE config changes, you never apply them.

## Inputs to read
1. `data/review_input.json` — the week's trades, decisions, skipped
   candidates, and current positions (pre-generated).
2. `README.md` — how the bot works and its config semantics.
3. `config.json` — current parameters.
4. Last ~40 lines of `logs/research_journal.md` — what the research layer
   believed this week.
5. `data/backtest_report.json` if present — long-run evidence.

## Analysis to perform
1. **Trade quality**: for each closed trade, was the exit reason sound?
   For open positions, is the thesis intact?
2. **Counterfactuals**: for the top skipped candidates in review_input.json,
   check what their price did afterwards (you may run
   `python3 -c "..."` with yfinance via Bash). Were the skips correct?
   Was anything bought that the confluence gate should have caught?
3. **Decision-log audit**: any pattern in skip reasons? (e.g. always failing
   the same confluence check might mean a miscalibrated threshold, or might
   mean the check is doing its job — distinguish using the counterfactuals.)
4. **Risk**: did stops trigger appropriately? Any position that breached
   small-to-medium risk expectations (>12% single-position loss)?

## Output
1. Write `logs/weekly_review_YYYY-MM-DD.md` (today's date) containing:
   - **Verdict**: one paragraph, plain English, no hedging.
   - **The week in numbers**: trades, P/L, win rate, current equity vs cash
     deposited to date.
   - **What worked / what didn't**: specific, evidence-backed.
   - **Proposed config changes**: max 3, each as
     `parameter: current -> proposed — reason`. Only propose changes the
     week's evidence actually supports; "no changes warranted" is a valid
     and often correct conclusion. NEVER propose disabling hard vetoes,
     raising max_position_usd above 100, or stops outside the 5-12 band.
2. Do NOT edit config.json or any bot code.

Keep the review under 60 lines. Evidence over vibes.
