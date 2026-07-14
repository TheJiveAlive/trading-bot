"""Box process watchdog with self-healing — runs on the box every 10 minutes.

Layer 1 (deterministic, local): checks every systemd unit, endpoint, agent
feed and disk; restarts failed services itself (bounded per day).

Layer 2 (AI, sandboxed): anything Layer 1 can't fix — failing workflows,
stale agent feeds, exhausted restart budgets — is packaged into a failure
report and dispatched to the GitHub 'medic' workflow, where Claude runs IN
THE EPHEMERAL SANDBOXED RUNNER (never on the box — the box only sends the
report), diagnoses against the repo, commits a fix, and emails what it did.

Complements bot.healthcheck (trading-subsystem checks, run manually);
this module is about PROCESSES and runs unattended.

State (restart counts, medic cooldowns) lives in ~/.bot/health_state.json.
"""
import datetime as dt
import json
import os
import subprocess
import urllib.request

REPO = "TheJiveAlive/trading-bot"
RH = os.path.expanduser("~/rh")
STATE = os.path.expanduser("~/.bot/health_state.json")
SECRETS = os.path.expanduser("~/.bot/secrets.json")
MAX_RESTARTS_PER_DAY = 3
MEDIC_COOLDOWN_H = 2

TIMERS = ["bot-session.timer", "bot-intel.timer", "bot-risk.timer",
          "cache-warm.timer", "night-screens.timer"]
SERVICES = ["lan-dashboard.service", "bot-monitor.service",
            "bot-webmonitor.service"]
ENDPOINTS = [("dashboard", "http://127.0.0.1:8080/"),
             ("webmonitor", "http://127.0.0.1:7682/monitor/")]
# unit -> port, for the port-conflict healer (both conflicts seen 2026-07-13:
# a stray pre-systemd process squatting the unit's port -> crashloop)
UNIT_PORTS = {"lan-dashboard.service": 8080, "bot-webmonitor.service": 7682}


def sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save(st):
    json.dump(st, open(STATE, "w"))


def _market_hours(now):
    et = now - dt.timedelta(hours=4)
    return et.weekday() < 5 and (9 * 60 + 30) <= (et.hour * 60 + et.minute) < 16 * 60


def _repair_git(st):
    """Deterministic repair for the empty-object corruption seen 2026-07-13
    (interrupted write left .git/objects files truncated; every pull failed).
    Exact sequence proven by hand that night. Bounded to once per day; local
    changes are STASHED (recoverable), never discarded."""
    if st.get("git_repaired") == st.get("day"):
        return None
    code, out = sh("git -C {} log -1 --oneline 2>&1".format(RH))
    if code == 0 and "bad object" not in out and "empty" not in out:
        return None
    st["git_repaired"] = st.get("day")
    steps = [
        "find {}/.git/objects -type f -empty -delete".format(RH),
        "git -C {} fetch origin".format(RH),
        "git -C {} update-ref refs/heads/main origin/main".format(RH),
        "git -C {} symbolic-ref HEAD refs/heads/main".format(RH),
        "git -C {} reset --mixed origin/main".format(RH),
        "git -C {} stash push -m boxwatch-git-repair -- .github bot research "
        "*.py 2>/dev/null || true".format(RH),
    ]
    for s in steps:
        sh(s, timeout=120)
    code, out = sh("git -C {} log -1 --oneline 2>&1".format(RH))
    return {"what": "git repo", "state": "corrupt (empty objects)",
            "action": "repaired: empties deleted, refetched, reset to origin/main"
            if code == 0 else "REPAIR FAILED: " + out[:80], "now": out[:60]}


def _free_port(unit, sysctl):
    """If a unit crashloops on EADDRINUSE, kill the squatter holding its port
    (only if it is NOT the unit's own process) and restart the unit."""
    port = UNIT_PORTS.get(unit)
    if not port:
        return False
    _, jout = sh("XDG_RUNTIME_DIR=/run/user/$(id -u) journalctl --user -u {} "
                 "-n 8 --no-pager 2>/dev/null".format(unit))
    if "Address already in use" not in jout:
        return False
    _, ssout = sh("ss -ltnp 2>/dev/null | grep ':{} '".format(port))
    import re
    m = re.search(r"pid=(\d+)", ssout)
    if not m:
        return False
    pid = m.group(1)
    _, mainpid = sh("systemctl --user show -p MainPID --value " + unit)
    if pid == mainpid.strip():
        return False
    sh("kill {} && sleep 2".format(pid))
    sysctl("restart " + unit)
    return True


def _local_diagnosis(report):
    """INSTANT local triage: a tool-less, single-turn Claude call (the same
    pattern as the pre-buy critic — judgment only, NO tools, NO edits, no
    agency on this host). Output is advisory: it rides along in the medic
    dispatch and the email; nothing it says is executed locally."""
    try:
        token = json.load(open(SECRETS)).get("claude_code_oauth_token", "")
        if not token:
            return None
        _, journal = sh("journalctl --user --since '-30 min' --no-pager -p warning 2>/dev/null | tail -30")
        prompt = (
            "You are the on-box triage brain for an automated trading bot host. "
            "A watchdog found problems it could not fix locally. Reply with ONLY "
            "a JSON object: {\"diagnosis\": one paragraph, \"likely_cause\": one "
            "line, \"recommended_commands\": [up to 4 shell commands a human "
            "could run], \"severity\": \"low|medium|high\"}. Failure report:\n"
            + json.dumps(report) + "\nRecent warnings from the journal:\n" + journal)
        env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=token)
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-opus-4-8",
             "--output-format", "json",
             "--allowedTools", "", "--max-turns", "1"],
            capture_output=True, text=True, timeout=120, env=env)
        body = json.loads(r.stdout).get("result", "")
        start, end = body.find("{"), body.rfind("}")
        return json.loads(body[start:end + 1]) if start >= 0 else None
    except Exception:
        return None


def check(now=None):
    """Returns (problems_fixed, problems_open). Each item is a dict."""
    now = now or dt.datetime.now(dt.timezone.utc)
    st = _state()
    today = now.strftime("%Y-%m-%d")
    if st.get("day") != today:
        st = {"day": today, "restarts": {}, "last_medic": st.get("last_medic", {})}
    fixed, open_ = [], []

    env = dict(os.environ, XDG_RUNTIME_DIR="/run/user/{}".format(os.getuid()))

    def sysctl(args):
        return subprocess.run("systemctl --user " + args, shell=True, env=env,
                              capture_output=True, text=True,
                              timeout=20).stdout.strip()

    # units: must be active; failed ones get restarted (bounded per day)
    for u in SERVICES + TIMERS:
        state = sysctl("is-active " + u)
        if state == "active":
            continue
        n = st["restarts"].get(u, 0)
        if n < MAX_RESTARTS_PER_DAY:
            sysctl("restart " + u)
            st["restarts"][u] = n + 1
            after = sysctl("is-active " + u)
            if after != "active" and _free_port(u, sysctl):
                after = sysctl("is-active " + u)
                if after == "active":
                    fixed.append({"what": u, "state": state,
                                  "action": "port squatter killed + restarted",
                                  "now": after})
                    continue
            (fixed if after == "active" else open_).append(
                {"what": u, "state": state,
                 "action": "restarted ({}/{})".format(n + 1, MAX_RESTARTS_PER_DAY),
                 "now": after})
        else:
            open_.append({"what": u, "state": state,
                          "action": "restart budget exhausted — needs medic"})

    # endpoints
    for name, url in ENDPOINTS:
        try:
            code = urllib.request.urlopen(url, timeout=8).status
        except Exception:
            code = 0
        if code != 200:
            open_.append({"what": "endpoint " + name,
                          "state": "HTTP {}".format(code),
                          "action": "unit restart already attempted above"})

    # heartbeat freshness (market hours only; session loop writes each cycle)
    if _market_hours(now):
        hb = os.path.join(RH, "data", "session_heartbeat.txt")
        try:
            age = (now - dt.datetime.fromisoformat(
                open(hb).read().strip().replace("Z", "+00:00"))).total_seconds()
            if age > 1200:
                open_.append({"what": "session heartbeat",
                              "state": "{:.0f}s stale".format(age),
                              "action": "trading loop may be wedged"})
        except Exception as e:
            open_.append({"what": "session heartbeat", "state": "unreadable",
                          "action": str(e)[:60]})
        # agent feeds should be <90 min old during the session
        for f in ("intel.json", "risk.json"):
            p = os.path.join(RH, "data", f)
            try:
                age_m = (now.timestamp() - os.path.getmtime(p)) / 60
                if age_m > 90:
                    open_.append({"what": f,
                                  "state": "{:.0f}m stale".format(age_m),
                                  "action": "agent dispatch chain may be broken"})
            except FileNotFoundError:
                pass

    # git repo health (empty-object corruption killed pulls once already)
    g = _repair_git(st)
    if g:
        (fixed if "repaired" in g["action"] else open_).append(g)

    # disk
    stv = os.statvfs("/")
    free_gb = stv.f_bavail * stv.f_frsize / 1e9
    if free_gb < 5:
        open_.append({"what": "disk", "state": "{:.1f}G free".format(free_gb),
                      "action": "low disk — needs cleanup"})

    # cloud workflows: latest run of each — failures need the medic, and a
    # workflow that hasn't run in too long is a SILENT miss (GitHub cron drops
    # runs — this is exactly how learnings went dark for 3 days undetected)
    STALE_MAX_H = {"overnight-learnings": 26}   # weekday-daily minimum cadence
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/{}/actions/runs?per_page=30".format(REPO),
            headers={"User-Agent": "tradinghost-boxwatch"})
        runs = json.load(urllib.request.urlopen(req, timeout=10)).get(
            "workflow_runs", [])
        seen, latest = set(), {}
        for r in runs:
            if r["name"] == "medic":
                continue
            latest.setdefault(r["name"], r)   # runs are newest-first
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            if r["status"] == "completed" and r["conclusion"] == "failure":
                open_.append({"what": "workflow " + r["name"],
                              "state": "latest run FAILED",
                              "action": "see " + r.get("html_url", "")})
        # staleness (weekday only — weekend gaps are expected for daily jobs)
        if now.weekday() < 5:
            for name, max_h in STALE_MAX_H.items():
                r = latest.get(name)
                if not r:
                    continue
                age_h = (now - dt.datetime.fromisoformat(
                    r["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
                if age_h > max_h:
                    open_.append({"what": "workflow " + name,
                                  "state": "last run {:.0f}h ago (max {}h)".format(
                                      age_h, max_h),
                                  "action": "scheduled run silently missed — "
                                  "check the box dispatch timer"})
    except Exception:
        pass

    _save(st)
    return fixed, open_


def dispatch_medic(report):
    """Fire the sandboxed medic workflow with the failure report. Cooldown-
    gated per failure signature so a broken thing can't spam Claude runs."""
    st = _state()
    sig = ",".join(sorted(p["what"] for p in report["open"]))[:120]
    last = st.get("last_medic", {}).get(sig)
    now = dt.datetime.now(dt.timezone.utc)
    if last and (now - dt.datetime.fromisoformat(last)).total_seconds() \
            < MEDIC_COOLDOWN_H * 3600:
        print("medic: cooldown active for this signature — not re-dispatching")
        return False
    token = json.load(open(SECRETS)).get("gh_workflow_token", "")
    if not token:
        print("medic: no workflow token")
        return False
    body = json.dumps({"ref": "main", "inputs": {
        "report": json.dumps(report)[:60000]}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/repos/{}/actions/workflows/medic.yml/dispatches"
        .format(REPO),
        data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "tradinghost-boxwatch"})
    code = urllib.request.urlopen(req, timeout=15).status
    st.setdefault("last_medic", {})[sig] = now.isoformat()
    _save(st)
    print("medic dispatched -> HTTP", code)
    return code == 204


def sync_repo():
    """Keep ~/rh in sync every 10 min. The working tree is perpetually dirty
    (renders + data files), which silently blocked every ad-hoc `pull
    --rebase` — 4 separate stale-code incidents on 2026-07-14 alone. One
    owner for sync: commit the data dirt, pull (-X theirs = local data wins
    conflicts), push. Code arrives; results leave."""
    sh("cd {} && git add -A >/dev/null 2>&1 && "
       "git -c user.name=trading-bot -c user.email=bot@local "
       "commit -q -m 'boxwatch sync' >/dev/null 2>&1".format(RH))
    for _ in range(3):
        code, _o = sh("cd {} && git pull --rebase -X theirs -q origin main "
                      "&& git push -q".format(RH), timeout=90)
        if code == 0:
            return True
    return False


def main():
    now = dt.datetime.now(dt.timezone.utc)
    sync_repo()
    fixed, open_ = check(now)
    for p in fixed:
        print("FIXED:", p)
    for p in open_:
        print("OPEN: ", p)
    if not fixed and not open_:
        print("healthy: units, endpoints, feeds, disk, workflows OK",
              now.strftime("%H:%M"))
        return
    report = {"host": "tradinghost", "at": now.isoformat(),
              "open": open_, "fixed_locally": fixed}
    if open_:
        # instant tool-less local triage rides along with the dispatch
        diag = _local_diagnosis(report)
        if diag:
            report["local_diagnosis"] = diag
            print("local diagnosis:", diag.get("likely_cause", ""))
        dispatch_medic(report)
    # best-effort email either way (self-heals included) so the human knows
    try:
        os.chdir(RH)
        from bot import config, notify
        config.load()
        lines = ["## Boxwatch report — {}".format(now.strftime("%H:%M UTC"))]
        for p in fixed:
            lines.append("- **self-healed**: {} ({})".format(p["what"], p["action"]))
        for p in open_:
            lines.append("- **OPEN**: {} — {} ({})".format(
                p["what"], p["state"], p["action"]))
        d = report.get("local_diagnosis")
        if d:
            lines += ["", "**Local triage** ({}): {}".format(
                d.get("severity", "?"), d.get("diagnosis", "")),
                "", "Suggested commands:"]
            lines += ["- `{}`".format(c) for c in d.get("recommended_commands", [])[:4]]
        if open_:
            lines.append("\nSandboxed medic dispatched (unless on cooldown).")
        notify.send_email("[bot boxwatch] {} self-healed, {} open".format(
            len(fixed), len(open_)), "\n".join(lines), markdown=True)
    except Exception as e:
        print("email skipped:", str(e)[:60])


if __name__ == "__main__":
    main()
