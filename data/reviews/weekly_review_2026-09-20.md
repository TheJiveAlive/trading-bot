# Weekly review — 2026-09-20

## Verdict
This was an execution-integrity week, not a strategy week. The signal/veto stack behaved
well — every skipped candidate I re-priced went nowhere or down, so the confluence and
hard-veto gates earned their keep. But the ledger is not to be trusted: trailing stops on
DVLT (7 attempts) and TPST (3 attempts) fired correctly yet never executed at the broker,
and each scan re-adopted the position ("broker is truth"), so the ~$7k/$9k "sells" in the
trade log are phantom and both names are still open. Two buys (ALTO, MNR×2) were broker-
rejected. Fix the T212 order pipeline and the DVLT/TPST exits before touching any dial.

## The week in numbers
- Cash: $933.60. Positions: 11 open. Equity ≈ $65.4k — but ~$64.0k of that is five *adopted*
  legacy broker lots (IQST/MVIS/RZLV/DVLT/TPST) that dwarf a nominally ~$670 (£100) demo
  account; the cash_sync log swings $67k→$1.4k→$0.9k. Treat equity as unreliable this week.
- Deposits to date: $0 (demo rehearsal; backtest seed $670).
- Genuinely new bot actions: 5 buys @ ~$100 (GRNT, ECVT, ASYS, EQPT, PLAY) = $497 deployed.
- Real closed trades: 0 → realized P/L ≈ $0 and win-rate is N/A this week (nothing truly closed).
- The 5 bot buys mark ≈ −0.6% (GRNT −2.4, ECVT −3.8, ASYS +1.6, EQPT +0.7, PLAY +0.9).
- Long-run context (backtest, Mar–Aug): +13.3% vs SPY +12.6%, 54.7% win, −14.2% max DD — engine is sound.

## What worked
- Veto calibration. Counterfactual prices 9/16→9/20: Z-vetoes ANGX (+0.0%), CSAN (+2.6%),
  URG (−2.5%); IV-vetoes HLMN (−1.7%), FRST (−1.4%), BORR (+2.3%), BDN (+0.0%); spread-veto
  CARL (+2.3%), TLACU (−0.2%). None ran away — no missed winners. Skips were correct.
- Research agreed with the vetoes on CARL (misread IPO buys) and CSAN (Raízen restructuring).

## What didn't
- **Broker execution.** DVLT/TPST stops never filled and re-loop every scan; ALTO and MNR
  (score 8.49) rejected outright. The trade log overstates activity that never happened.
- **EQPT bought same-day it was research-flagged.** The 9/18 journal added EQPT to *avoid*
  (class action, 9/21 deadline) yet the 16:43 buy went through — the avoid list wasn't applied.
- **Weakest entries came in via risk_on.** ASYS (4.8) and ALTO (4.89) cleared the gate only
  because `force_regime: risk_on` lowers the buy threshold 0.5 (5.25→4.75); both are flat/dead.
- No position breached the >12% single-loss rule vs cost (worst: DVLT −9.7%, TPST −9.5%).

## Proposed config changes
- `force_regime: "risk_on" -> null` — the research layer called RISK_OFF→NEUTRAL *every day*
  this week (Fed hiked to 3.75–4.00%, Brent >$100, 10-yr ~5%); forcing lowest-threshold /
  widest-stop aggression into that tape is what admitted the 4.8/4.89 entries. Restoring the
  adaptive blend raises the gate and tightens stops. Reversible, touches no veto or cap.
- `min_composite_score: 5.25 -> 5.5` — only if risk_on is kept; restores the tune-backed
  posture the config's own note endorses and would have excluded this week's dead sub-5.5 buys.
- No other tuning warranted — the vetoes are well-calibrated and the real defect is execution/
  recon integrity (DVLT high-water reset + forced exit, order-fill confirmation), not parameters.
