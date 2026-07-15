#!/usr/bin/env python3
"""Stress test (python -m bot.stresstest): run every compute job back-to-back, sample CPU/RAM at
1Hz throughout, email the peaks + per-job results. Run from ~/rh."""
import json
import os
import subprocess
import sys
import threading
import time

# self-bootstrap: the stress-test emailer failed its first run because the
# parent process lacked PYTHONPATH (2026-07-14) — never depend on caller env
ROOT = os.path.expanduser("~/rh")
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PY = os.path.expanduser("~/bot/venv/bin/python")

JOBS = [
    ("finbert",      [PY, "-m", "bot.finbert"]),
    ("screens",      [PY, "-m", "bot.screens"]),
    ("dataaudit",    [PY, "-m", "bot.dataaudit"]),
    ("quantregime",  [PY, "-m", "bot.quantregime"]),
    ("lorentzian",   [PY, "-m", "bot.lorentzian"]),
    ("boxwatch",     [PY, "-m", "bot.boxwatch"]),
    ("displaycheck", [PY, "-m", "bot.displaycheck"]),
    ("walkforward",  [PY, "backtest.py", "--walkforward"]),
]

samples = []
stop = threading.Event()


def _cpu_snap():
    v = [int(x) for x in open("/proc/stat").readline().split()[1:9]]
    return v[3] + v[4], sum(v)


def sampler():
    prev = _cpu_snap()
    while not stop.is_set():
        time.sleep(1)
        cur = _cpu_snap()
        didle, dtot = cur[0] - prev[0], cur[1] - prev[1]
        prev = cur
        cpu = 100.0 * (1 - didle / dtot) if dtot else 0.0
        mt = ma = 0
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemTotal"):
                mt = int(ln.split()[1])
            elif ln.startswith("MemAvailable"):
                ma = int(ln.split()[1])
                break
        used_gb = (mt - ma) / 1048576.0
        try:
            top = subprocess.run(
                "ps -eo comm,%cpu --sort=-%cpu | sed -n 2p", shell=True,
                capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            top = "?"
        samples.append({"t": time.time(), "cpu": cpu, "mem_gb": used_gb,
                        "top": top, "job": samples_job[0]})


samples_job = ["idle"]
th = threading.Thread(target=sampler, daemon=True)
th.start()

results = []
for name, cmd in JOBS:
    samples_job[0] = name
    t0 = time.time()
    env = dict(os.environ, PYTHONPATH=os.path.expanduser("~/rh"))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=2400,
                           env=env)
        ok = r.returncode == 0
        err = "" if ok else (r.stderr.strip().splitlines() or ["?"])[-1][:120]
    except Exception as e:
        ok, err = False, str(e)[:120]
    dur = time.time() - t0
    js = [s for s in samples if s["job"] == name]
    peak_cpu = max((s["cpu"] for s in js), default=0)
    peak_mem = max((s["mem_gb"] for s in js), default=0)
    results.append({"job": name, "ok": ok, "sec": round(dur, 1),
                    "peak_cpu": round(peak_cpu, 1),
                    "peak_mem_gb": round(peak_mem, 2), "err": err})
    print("{:12s} {} {:6.1f}s  cpu {:5.1f}%  mem {:.2f}G  {}".format(
        name, "OK " if ok else "FAIL", dur, peak_cpu, peak_mem, err), flush=True)

stop.set()
time.sleep(1.5)

overall_cpu = max((s["cpu"] for s in samples), default=0)
overall_mem = max((s["mem_gb"] for s in samples), default=0)
hot = max(samples, key=lambda s: s["cpu"], default=None)

lines = ["## Stress test — every compute job back-to-back",
         "",
         "**Peak CPU: {:.1f}%**  ·  **Peak memory: {:.2f} GB** of 14.9 GB".format(
             overall_cpu, overall_mem)]
if hot:
    lines.append("Hottest moment: `{}` during **{}** (top process: {})".format(
        time.strftime("%H:%M:%S UTC", time.gmtime(hot["t"])), hot["job"], hot["top"]))
lines += ["", "| Job | Result | Duration | Peak CPU | Peak Mem |",
          "|---|---|---|---|---|"]
for r in results:
    lines.append("| {} | {} | {:.0f}s | {:.0f}% | {:.2f} GB |".format(
        r["job"], "✅" if r["ok"] else "❌ " + r["err"], r["sec"],
        r["peak_cpu"], r["peak_mem_gb"]))
fails = [r for r in results if not r["ok"]]
lines += ["", "**{} of {} jobs passed.**".format(len(results) - len(fails), len(results))]

body = "\n".join(lines)
print(body)
try:
    from bot import config, notify
    config.load()
    notify.send_email("[bot] stress test: {} jobs, peak CPU {:.0f}%, peak mem {:.1f}G".format(
        len(results), overall_cpu, overall_mem), body, markdown=True)
    print("EMAIL SENT")
except Exception as e:
    print("EMAIL FAILED:", str(e)[:200])

json.dump({"results": results, "peak_cpu": overall_cpu,
           "peak_mem_gb": overall_mem},
          open(os.path.expanduser("~/data/pwb/stresstest.json"), "w"), indent=1)
