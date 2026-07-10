# Weekly Trading Bot Review — 2026-07-10

**Verdict:** A genuinely quiet, healthy week. The account was scaled from
its $127/month paper budget to a $100k test book on 2026-07-07, so this is
really 3 trading days of data at the new size, not a full week — treat every
number below as low-confidence. In that window the bot made one small,
correctly-stopped-out loser (VMAR, pre-dating the scale-up) and three new
buys that are all modestly green. More importantly, every single skip this
week — six confluence/dilution-veto rejections plus two Reddit-wildcard
skips — was validated by subsequent price action: vetoed names fell or went
nowhere, bought names rose. The gates are doing their job. No config changes
are warranted on this little evidence; one operational risk (stop-check
cadence) is worth watching, not tuning.

## The week in numbers
- Trades: 4 buys, 1 sell (1 closed round-trip: VMAR).
- Closed P/L: VMAR -$9.45 (-16.0%), win rate 0/1 (n=1, not meaningful).
- Open positions: AVO +1.5%, LRMR +4.4%, WRAP +0.2% (all opened this week).
- Equity $100,533.83 vs $100,059.22 deposited-to-date ($127 monthly + $99,932.22
  test injection on 07-07) → +$474.61 (+0.47%) since scale-up, 3 days in.
- No circuit breaker (drawdown/daily-loss) events; no sector-cap vetoes fired.

## What worked
- **Dilution/spread vetoes were all correct.** ABSI (spread 50%, dilution
  filing 14d ago) fell 11.10→10.64 after the skip. BOLD (spread 31%) fell
  2.51→2.42. EVMN (spread 14%, IV 233%, dilution filing 10d ago) fell
  13.51→13.18. PRQR (dilution filing 3d ago) fell 1.76→1.71. VII-UN (dilution,
  4 filings/90d) was flat ~$10.00 as expected for a SPAC unit. RIG (3/8
  confluence) was roughly flat. Six for six — the gate isn't over-blocking.
- **VMAR avoid-list call was right.** Research flagged it same-day (reverse
  split + $52k insider sale); it kept sliding all week (1.41→1.18) and the
  trailing stop closed it for a small, correctly-sized loss.
- **LRMR held through a scare correctly.** A 17% single-day drop on an
  anaphylaxis safety signal (07-06) didn't trigger the stop, and a 07-08
  director buy ($166.5k) confirmed the thesis was still intact — now +4.4%.

## What didn't
- **WRAP was a marginal entry.** Bought at $2.41 right after a 36% one-day
  pop (07-09: $1.73→$2.36), on only 5/8 confluence — failing unusual_volume,
  price_action (i.e. already extended), and clean_dilution_history
  simultaneously. It cleared the ≥4-pass bar by exactly one. High insider/
  breakout score (10.45) is doing a lot of the work here; worth watching
  next week rather than acting on now (n=1, still +0.2%).
- **Stop-check cadence, not stop width.** VMAR's exit fired as "trailing
  stop (7%)" but executed 16.0% off the high — the scan only runs a few
  times a day, so a gapping penny stock can blow through the intended stop
  before the next check. Harmless here ($9.45 on a pre-scale-up $59
  position) but the same gap on a current $5-8k position would be a real
  loss. This isn't a config.json lever (it's the scan schedule, not
  `trailing_stop_pct`), so no proposal below — flagging for awareness.
- All three buys failed `clean_dilution_history` (chronic-diluter flag)
  without tripping the hard veto (no *recent* filing). Not yet a problem —
  all three are green — but 3/3 is worth tracking, not dismissing.

## Proposed config changes
No changes warranted. Three days of data at the new account size, one
closed trade, and a clean sweep on skip counterfactuals is not enough
evidence to move any threshold. Revisit `min_composite_score` (5.5, raised
2026-07-10) and the WRAP-style marginal-confluence pattern once there are
more closed trades to judge them by.
