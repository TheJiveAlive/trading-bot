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

    # disk
    stv = os.statvfs("/")
    free_gb = stv.f_bavail * stv.f_frsize / 1e9
    if free_gb < 5:
        open_.append({"what": "disk", "state": "{:.1f}G free".format(free_gb),
                      "action": "low disk — needs cleanup"})

    # cloud workflows: latest run of each — failures need the medic
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/{}/actions/runs?per_page=15".format(REPO),
            headers={"User-Agent": "tradinghost-boxwatch"})
        runs = json.load(urllib.request.urlopen(req, timeout=10)).get(
            "workflow_runs", [])
        seen = set()
        for r in runs:
            if r["name"] in seen or r["name"] == "medic":
                continue
            seen.add(r["name"])
            if r["status"] == "completed" and r["conclusion"] == "failure":
                open_.append({"what": "workflow " + r["name"],
                              "state": "latest run FAILED",
                              "action": "see " + r.get("html_url", "")})
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


def main():
    now = dt.datetime.now(dt.timezone.utc)
    fixed, open_ = check(now)
    for p in fixed:
        print("FIXED:", p)
    for p in open_:
        print("OPEN: ", p)
    if not fixed and not open_:
        print("healthy: units, endpoints, feeds, disk, workflows OK",
              now.strftime("%H:%M"))
    if open_:
        dispatch_medic({"host": "tradinghost", "at": now.isoformat(),
                        "open": open_, "fixed_locally": fixed})


if __name__ == "__main__":
    main()
