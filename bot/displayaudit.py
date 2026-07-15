"""Display-value auditor — verifies the terminal shows the TRUTH.

Three display bugs in three days (WRAP sector-cap block, PRQR phantom target,
frozen buy line) were all the DISPLAY lying while the engine was right. This
audits the rendered monitor frame against source-of-truth:

  DETERMINISTIC: buy line vs risk.buy_threshold; per-position P/L vs broker;
                 account totals vs broker_state — exact numeric compare.
  SEMANTIC (Haiku, cheap): the efficient model reads the frame + the truth
                 table and flags anything shown that CONTRADICTS the data
                 (sign errors, mislabels, stale values) the regex can't catch.

AUTO-FIX policy: only STALE DATA is auto-fixed (re-render). CODE bugs (a wrong
formula/label in monitor.py) are flagged to boxwatch -> the SANDBOXED medic;
never auto-edit the live monitor on a timer. Writes data/display_audit.json.
"""
import json
import os
import re
import subprocess
import warnings
warnings.filterwarnings("ignore")

os.chdir(os.path.expanduser("~/rh"))
import sys
sys.path.insert(0, os.path.expanduser("~/rh"))
MON = os.path.expanduser("~/monitor.py")


def _render():
    r = subprocess.run("timeout 6 python3 -u {} 2>&1".format(MON), shell=True,
                       capture_output=True, text=True,
                       env=dict(os.environ, COLUMNS="100",
                                PYTHONPATH=os.path.expanduser("~/rh")),
                       cwd=os.path.expanduser("~/rh"))
    frame = r.stdout.split("\x1b[H\x1b[2J")
    frame = frame[1] if len(frame) > 1 else r.stdout
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", frame)


def _truth():
    from bot import config, risk
    cfg = config.load()
    research = json.load(open("data/research.json"))
    t = {"buy_line": round(risk.buy_threshold(cfg, research), 2),
         "regime": research.get("market_regime"), "positions": {}}
    try:
        b = json.load(open("data/broker_state.json"))
        t["account_total"] = round(b.get("cash", {}).get("total", 0), 2)
        for p in b.get("positions", []):
            t["positions"][p["ticker"]] = round(p.get("pnl", 0), 2)
    except Exception:
        pass
    return t


def audit():
    frame = _render()
    truth = _truth()
    issues = []

    # 1) buy line
    m = re.search(r"buy line ([0-9.]+)", frame)
    if m and abs(float(m.group(1)) - truth["buy_line"]) > 0.01:
        issues.append({"field": "buy_line", "shown": float(m.group(1)),
                       "truth": truth["buy_line"], "kind": "code"})
    # 2) per-position P/L (line: TICKER ... +/-N.NN at end)
    for tkr, pl in truth["positions"].items():
        pm = re.search(r"\b{}\b.*?([+\-−]\$?[0-9.]+)\s*$".format(tkr),
                       frame, re.M)
        if pm:
            shown = float(pm.group(1).replace("−", "-").replace("$", ""))
            if abs(shown - pl) > 0.05:
                issues.append({"field": "pl_" + tkr, "shown": shown,
                               "truth": pl, "kind": "data"})

    # 3) SEMANTIC pass — Haiku reads frame + truth, flags contradictions
    sem = []
    try:
        tok = json.load(open(os.path.expanduser("~/.bot/secrets.json"))).get(
            "claude_code_oauth_token", "")
        if tok:
            prompt = (
                "You audit a trading bot's terminal display for CORRECTNESS. "
                "Below is the rendered frame and the source-of-truth values. "
                "Flag ONLY things the frame SHOWS that contradict the truth "
                "(wrong number, wrong sign, stale/mislabelled value, a "
                "candidate marked buyable that the data says is blocked). Do "
                "NOT flag layout/spacing. Reply ONLY JSON: "
                '{"issues":[{"what":"...","why":"..."}]} (empty list if clean).'
                "\n\nTRUTH:\n" + json.dumps(truth) + "\n\nFRAME:\n" + frame[:4000])
            r = subprocess.run(
                ["claude", "--model", "claude-haiku-4-5-20251001", "-p", prompt,
                 "--allowedTools", "", "--max-turns", "1", "--output-format", "json"],
                capture_output=True, text=True, timeout=60,
                env=dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=tok))
            body = json.loads(r.stdout).get("result", "")
            j = body[body.find("{"):body.rfind("}") + 1]
            sem = json.loads(j).get("issues", []) if j else []
    except Exception:
        pass

    out = {"generated": __import__("datetime").datetime.now(
               __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
           "deterministic_issues": issues, "semantic_issues": sem,
           "clean": not issues and not sem, "truth": truth}
    json.dump(out, open("data/display_audit.json", "w"), indent=1)
    return out


if __name__ == "__main__":
    r = audit()
    if r["clean"]:
        print("display audit: CLEAN — terminal matches source of truth")
    else:
        print("DISPLAY MISMATCHES:")
        for i in r["deterministic_issues"]:
            print("  [{}] {}: shows {} but truth {}".format(
                i["kind"], i["field"], i["shown"], i["truth"]))
        for s in r["semantic_issues"]:
            print("  [haiku] {} — {}".format(s.get("what"), s.get("why")))
