# Medic Log

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
