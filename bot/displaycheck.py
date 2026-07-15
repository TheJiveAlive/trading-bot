"""Display-integrity check — no information held hostage.

1. LINT: flags any hard-coded truncation ([:N], 36<=N<=100) in monitor.py
   that is not width-scaled ([:W-k]) — the regression that caused the
   2026-07-15 truncation bug.
2. RENDER: runs one monitor frame at 66 and 120 columns; verifies every
   expected section renders and no line overflows the terminal width
   (overflow = broken layout, missing = lost panel).

Run via the stress test battery or directly: python -m bot.displaycheck
"""
import os
import re
import subprocess

MON = os.path.expanduser("~/monitor.py")
SECTIONS = ["TRADING BOT", "ACCOUNT", "POSITIONS", "BUY RADAR",
            "CLAUDE AI", "BOT ACTIVITY"]


def lint():
    src = open(MON).read()
    bad = []
    for m in re.finditer(r"\[:(\d+)\]", src):
        n = int(m.group(1))
        if 36 <= n <= 100:
            line = src[:m.start()].count("\n") + 1
            bad.append("monitor.py:{} hard truncation [:{}] — use [:W-k]".format(line, n))
    return bad


def render(cols):
    env = dict(os.environ, COLUMNS=str(cols), PYTHONPATH=os.path.expanduser("~/rh"))
    r = subprocess.run("timeout 6 python3 -u {} 2>&1".format(MON), shell=True,
                       capture_output=True, text=True, env=env,
                       cwd=os.path.expanduser("~/rh"))
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", r.stdout)
    frame = plain.split("\x1b")[0] if "\x1b" in plain else plain
    lines = [l for l in frame.splitlines() if l.strip()]
    problems = []
    for s in SECTIONS:
        if not any(s in l for l in lines):
            problems.append("{}col: section MISSING: {}".format(cols, s))
    over = [l for l in lines if len(l) > cols + 2]
    if over:
        problems.append("{}col: {} lines overflow width (worst {})".format(
            cols, len(over), max(len(l) for l in over)))
    return problems


def run():
    problems = lint()
    for c in (66, 120):
        problems += render(c)
    return problems


if __name__ == "__main__":
    p = run()
    if p:
        print("DISPLAY PROBLEMS ({}):".format(len(p)))
        for x in p:
            print("  -", x)
    else:
        print("display integrity OK — width-scaled, all sections render at 66 and 120 cols")
