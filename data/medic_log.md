# Medic Log

## 2026-07-15 — terminal shows buy line 6.0 vs truth 5.25 (monitor.py, box-local)

**Report:** `FAILURE_REPORT.json` from tradinghost at 2026-07-15T13:32:40Z. One
open item: terminal "shows wrong values" — display audit found `buy_line` shown
`6.0` while truth is `5.25`, `kind=code`. `fixed_locally` empty. Local diagnosis:
render/computation bug in the display path (wrong variable / rounding-ceil /
regime-adjusted value), coincident with `goldbot-cnews.service` failing to start
(start timed out, SIGTERM 15); high severity.

**Investigation:**
- Source of truth is correct. `risk.buy_threshold(cfg, research)` = `5.25`
  (`config.json` `buying.min_composite_score` = 5.25 + neutral-regime adj 0.0).
  Verified live: `research.json` is **fresh** (date 2026-07-15, regime
  `neutral`), and the function returns 5.25. `data/display_audit.json` truth
  block agrees (`buy_line: 5.25`).
- Because the current regime is neutral and research is fresh, the stale-regime
  theory (goldbot-cnews hang feeding a stale adjustment) is **ruled out**: 5.25
  is already the correct neutral value. The auditor's `kind=code` confirms this
  is a formula defect in the renderer, not stale data.
- Every **repo-side** renderer is correct — both `bot/preopen_brief.py:82` and
  `bot/dashboard.py` (1887/2232/2292) call `risk.buy_threshold` and would print
  5.25. `git grep` finds no repo code that emits "buy line 6.0".
- The wrong `6.0` is produced by the terminal monitor the auditor renders,
  `~/monitor.py` (`bot/displayaudit.py:27` `MON = ~/monitor.py`). That file is
  **not in this repo** (`git ls-files` has no monitor.py; it lives beside the
  `~/rh` checkout, not inside it). It is not importing `risk.buy_threshold` — if
  it were, it would show 5.25 — so it carries its own divergent formula. `6.0`
  is consistent with `ceil(5.25)` / round-up, or a hardcoded base+regime.
- `goldbot-cnews.service` start-timeout is a systemd/host issue; not reachable
  from the sandbox and, per the above, not the cause of the display number.

**Classification:** Both items **BOX-LOCAL**. The buggy renderer (`~/monitor.py`)
and the timed-out unit both live only on tradinghost. Not repo-fixable.

**Action taken:** No code / config / workflow change. The repo's source of truth
and all repo renderers are already correct at 5.25; per the hard rules a
speculative edit would not touch the broken component (the box-local monitor) and
would violate "minimal diff / no drive-by". Emailed the human the exact fix for
`~/monitor.py` (point its buy-line render at `risk.buy_threshold(cfg, research)`
formatted `{:.2f}`, dropping any local ceil/duplicated formula) plus the
systemd/journal diagnostics and restart for `goldbot-cnews.service`. Operator
risk noted: the terminal reads ~14% high (6.0 vs 5.25) but the **engine trades
against the correct 5.25** — display-only, no trade impact.

## 2026-07-14 — risk.json 203m stale (risk dispatch leg dark)

**Report:** `FAILURE_REPORT.json` from tradinghost at 2026-07-14T17:43:05Z. One
open item: `risk.json` ~203m stale, "agent dispatch chain may be broken".
`fixed_locally` empty. Local triage: high severity, silent stall of the
risk.json producer.

**Investigation:**
- `data/risk.json` last `generated` = 2026-07-14T14:38:00Z (~10:38 ET).
- `data/intel.json` last `generated` = 2026-07-14T17:32:00Z — **fresh** (11 min
  before the report). Intel and risk share the exact same cloud pattern (box
  timer → `workflow_dispatch` → Claude in the ephemeral runner → commit → box
  pull-back), the same GH dispatch token, and the same Claude auth.
- Since intel's full chain succeeded at 17:32, the shared infrastructure is
  healthy and Claude is **not** usage-limited/rate-limited (that would have
  blocked intel too). The failure is isolated to the **risk-specific leg**.
- boxwatch (`bot/boxwatch.py`) reported no failed cloud run for `risk-officer`
  and `bot-risk.timer` was not in the restart/open list → the timer shows
  `is-active`, but boxwatch only checks the `.timer` active state, not whether
  the oneshot dispatch `.service` it launches actually succeeds, and
  `risk-officer` is not in its `STALE_MAX_H` cloud-staleness map — so a wedged
  risk dispatch surfaces ONLY via the 90-min feed-age check. Consistent with a
  silent dispatch failure.
- `SCHEDULING.md`: intel/prices/scan/research/review/learnings each have an
  external cron-job.org pinger as a backup dispatcher; **risk.yml is NOT in
  that table** — risk is dispatched *only* by the box's `bot-risk.timer`. So a
  box-side dispatch hiccup leaves intel alive (external pinger) but takes risk
  dark. Exactly the observed symptom.
- Repo-side risk files are healthy: `.github/workflows/risk.yml` and
  `research/risk_prompt.md` are valid and mirror the working intel path.

**Classification:** BOX-LOCAL (single point of failure: `bot-risk.timer` /
its dispatch service on tradinghost). Not repo-fixable.

**Action taken:** No code, config, or workflow change (risk.yml and
risk_prompt.md are healthy; a speculative edit would not touch the broken
component, which is on the host). Emailed the human the exact systemd/journal
diagnostics for the `bot-risk` unit, a one-line manual dispatch to close the
stale-data gap immediately, and two optional robustness follow-ups (add risk.yml
to the cron-job.org pinger table for dispatch redundancy; have boxwatch check
the triggered dispatch service, not just the timer's active state). Risk gates
are evaluating against ~3h-old data until re-dispatched — flagged as high
priority.

## 2026-07-13 — medic-drill (SYNTHETIC TEST)

**Report:** `FAILURE_REPORT.json` from tradinghost at 2026-07-13T21:27:06Z flagged a single open item, `medic-drill`, explicitly marked as a synthetic end-to-end test of the medic chain. Nothing was actually broken; `fixed_locally` was empty.

**Classification:** TRANSIENT (drill, no real fault).

**Action taken:** None. No investigation of bot modules/config was needed or performed since the report stated nothing was broken. No code, config, or trading parameter changes made.

**Outcome:** Confirmation email sent to the human noting the medic chain (dispatch → triage → log → email) completed successfully end-to-end.
