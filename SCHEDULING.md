# Reliable scheduling via external cron pinger

GitHub's built-in scheduler drops jobs (best-effort, throttled on public repos).
This routes reliable triggers through **cron-job.org** (free) calling GitHub's
API. The workflows keep their internal `schedule:` as a backup, but the pinger
is what makes them fire on time.

## Step 1 — create a GitHub token (once)

1. Go to https://github.com/settings/personal-access-tokens/new
   (Settings → Developer settings → Fine-grained personal access tokens)
2. Name: `cron-pinger`. Expiration: your choice (set a reminder to rotate).
3. **Repository access** → Only select repositories → `TheJiveAlive/trading-bot`
4. **Permissions** → Repository permissions → **Actions: Read and write**
   (that is the ONLY permission needed — nothing else)
5. Generate, copy the token (starts `github_pat_...`). Keep it safe.

This token can ONLY trigger workflows on this one repo — it cannot touch your
account, other repos, or any secrets.

## Step 2 — create the pinger jobs at cron-job.org (free)

Sign up at https://cron-job.org, then **Create cronjob** for each row below.

For every job use:
- **Request method**: POST
- **Headers**:
  - `Authorization: Bearer github_pat_YOUR_TOKEN`
  - `Accept: application/vnd.github+json`
- **Request body**: `{"ref":"main"}`

| Job | URL (…/actions/workflows/**FILE**/dispatches) | Schedule (UTC) |
|---|---|---|
| Live prices | `https://api.github.com/repos/TheJiveAlive/trading-bot/actions/workflows/prices.yml/dispatches` | every 5 min, 13:30–20:00, Mon–Fri |
| Trading scan | `https://api.github.com/repos/TheJiveAlive/trading-bot/actions/workflows/scan.yml/dispatches` | every 30 min, 13:30–20:00, Mon–Fri |
| Hourly intel | `https://api.github.com/repos/TheJiveAlive/trading-bot/actions/workflows/intel.yml/dispatches` | 14:08, 17:08, 20:08, Mon–Fri |
| Daily research | `https://api.github.com/repos/TheJiveAlive/trading-bot/actions/workflows/research.yml/dispatches` | 12:37, Mon–Fri |
| Weekly review | `https://api.github.com/repos/TheJiveAlive/trading-bot/actions/workflows/review.yml/dispatches` | 16:03, Sun |
| Overnight learnings | `https://api.github.com/repos/TheJiveAlive/trading-bot/actions/workflows/learnings.yml/dispatches` | 02:17, Tue–Sat |

cron-job.org lets you set the schedule with its own UI (day-of-week + time
windows + interval). Times are UTC.

## Notes
- A manual "Run workflow" in the GitHub Actions tab always works too, and now
  forces a full scan during market hours.
- If a ping returns HTTP 204 → success. 401 → token wrong. 404 → check the
  repo/file path.
- The internal `schedule:` crons remain as a fallback if the pinger is down.
