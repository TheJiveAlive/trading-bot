"""Hiring-velocity pulse — public ATS job boards as an operational-health tell.

For holdings + top candidates, probes the public Greenhouse/Lever JSON boards
(slug guessed from company name), snapshots open-role counts into
jobs_pulse.db, and flags big drops (>=30% with a meaningful base) into
data/jobs_pulse.json — a quiet posting-pull often precedes bad news.

HONEST SCOPE: no TCN until years of history exist (the archive builds it);
slug-guessing misses many microcaps (fail-silent, only found boards report);
the flag feeds the RISK OFFICER as a lead to verify, never a score input.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import urllib.request

from bot.config import DATA_DIR

OUT = os.path.join(DATA_DIR, "jobs_pulse.json")
DB = os.path.join(DATA_DIR, "jobs_pulse.db")
UA = {"User-Agent": "Mozilla/5.0 tradinghost-jobs"}


def _get(url, timeout=10):
    try:
        return json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=timeout))
    except Exception:
        return None


def _count_openings(name):
    """(count, source) via Greenhouse then Lever public boards, or None."""
    slug = re.sub(r"[^a-z0-9]", "", (name or "").lower()
                  .replace(" inc", "").replace(" corp", "").replace(" ltd", ""))
    if not slug:
        return None
    d = _get("https://boards-api.greenhouse.io/v1/boards/{}/jobs".format(slug))
    if d and "jobs" in d:
        return len(d["jobs"]), "greenhouse"
    d = _get("https://api.lever.co/v0/postings/{}?mode=json".format(slug))
    if isinstance(d, list):
        return len(d), "lever"
    return None


def run():
    from bot import market
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS pulse (date TEXT, ticker TEXT, "
                "openings INTEGER, source TEXT, PRIMARY KEY(date,ticker))")
    led = sqlite3.connect(os.path.join(DATA_DIR, "ledger.db"))
    held = [r[0] for r in led.execute(
        "SELECT ticker FROM positions WHERE status='open'")]
    last = led.execute("SELECT MAX(ts) FROM scan_candidates").fetchone()[0]
    cands = [r[0] for r in led.execute(
        "SELECT DISTINCT ticker FROM scan_candidates WHERE ts=?",
        (last,))][:8] if last else []
    led.close()

    today = dt.date.today().isoformat()
    flags, tracked = [], {}
    for t in dict.fromkeys(held + cands):
        try:
            name = (market.ticker_info(t) or {}).get("shortName", "")
        except Exception:
            name = ""
        r = _count_openings(name)
        if not r:
            continue
        n, src = r
        con.execute("INSERT OR REPLACE INTO pulse VALUES (?,?,?,?)",
                    (today, t, n, src))
        prev = con.execute(
            "SELECT openings FROM pulse WHERE ticker=? AND date<? "
            "ORDER BY date DESC LIMIT 1", (t, today)).fetchone()
        tracked[t] = {"openings": n, "prev": prev[0] if prev else None,
                      "source": src, "held": t in held}
        if prev and prev[0] >= 5 and n < prev[0] * 0.7:
            flags.append({"ticker": t, "held": t in held,
                          "openings": n, "was": prev[0],
                          "note": "posting-pull {}->{} — possible hiring "
                                  "freeze; risk officer verify".format(prev[0], n)})
    con.commit()
    con.close()
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "tracked": tracked, "flags": flags,
           "note": ("Public-ATS headcount pulse. Archive feeds a future "
                    "velocity model; flags are risk-officer LEADS, not scores.")}
    json.dump(out, open(OUT, "w"), indent=1)
    return out


if __name__ == "__main__":
    r = run()
    print("jobs pulse: {} boards found, {} flags".format(
        len(r.get("tracked", {})), len(r.get("flags", []))))
    for t, v in r.get("tracked", {}).items():
        print("  {:6s} {} openings ({})".format(t, v["openings"], v["source"]))
