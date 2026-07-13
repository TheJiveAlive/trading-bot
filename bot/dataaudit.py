"""Nightly data-trust audit — cross-references every price source we have.

Runs on the box after the universe screens (night-screens.service). For the
tickers that matter (holdings, top candidates, plus a random cache sample):

  1. bars.db vs FRESH Yahoo closes (last 5 sessions, >2% disagreement flagged)
  2. staleness   — cache stopped updating for a ticker Yahoo still quotes
  3. flat-lines  — five identical closes = dead/ghost data
  4. broker truth — T212's live position price vs our cached close (>3%);
     the broker is the account of record, so it wins every dispute

Results land in data/data_quality.json. The overnight Claude study session
reviews the report (study prompt item 5) and the risk officer is told when a
HELD ticker's data disagrees — that is the "Claude makes sure the data is
correct" loop: code measures, Claude judges, verdicts land in learnings.md.
"""
import datetime as dt
import json
import os
import random

from bot.config import DATA_DIR
from bot import barcache

OUT = os.path.join(DATA_DIR, "data_quality.json")
PCT_FLAG = 0.02       # bars.db vs Yahoo disagreement threshold
BROKER_FLAG = 0.03    # broker live price vs cache close threshold
SAMPLE_RANDOM = 20


def _watch_tickers():
    """Holdings + latest candidates + random cache sample."""
    import sqlite3
    tickers, held = [], []
    try:
        con = sqlite3.connect(os.path.join(DATA_DIR, "ledger.db"))
        held = [r[0] for r in con.execute(
            "SELECT ticker FROM positions WHERE status='open'")]
        last_ts = con.execute(
            "SELECT MAX(ts) FROM scan_candidates").fetchone()[0]
        cands = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM scan_candidates WHERE ts=?",
            (last_ts,))] if last_ts else []
        con.close()
        tickers = held + [c for c in cands if c not in held]
    except Exception:
        pass
    try:
        con = barcache._con()
        pool = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM bars ORDER BY RANDOM() LIMIT ?",
            (SAMPLE_RANDOM,))]
        con.close()
        tickers += [t for t in pool if t not in tickers]
    except Exception:
        pass
    return tickers, set(held)


def audit():
    import pandas as pd
    import yfinance as yf
    now = dt.datetime.now(dt.timezone.utc)
    tickers, held = _watch_tickers()
    if not tickers:
        return {}

    # cached last-5 closes per ticker
    con = barcache._con()
    cached = {}
    for t in tickers:
        rows = con.execute(
            "SELECT date, close FROM bars WHERE ticker=? "
            "ORDER BY date DESC LIMIT 5", (t,)).fetchall()
        if rows:
            cached[t] = rows            # newest first
    con.close()

    issues, checked = [], 0
    fresh = {}
    try:
        df = yf.download(tickers, period="7d", interval="1d", progress=False,
                         group_by="ticker", threads=True, auto_adjust=True)
        for t in tickers:
            try:
                sub = (df[t] if len(tickers) > 1 else df)["Close"].dropna()
                fresh[t] = {ix.strftime("%Y-%m-%d"): float(v)
                            for ix, v in sub.items()}
            except Exception:
                continue
    except Exception:
        pass

    for t in tickers:
        rows = cached.get(t)
        ys = fresh.get(t)
        if not rows:
            continue
        checked += 1
        # 1) cross-source disagreement on overlapping dates
        if ys:
            for d, c in rows:
                y = ys.get(d)
                if y and c > 0 and abs(y - c) / c > PCT_FLAG:
                    issues.append({"ticker": t, "kind": "source_mismatch",
                                   "date": d, "cache": round(c, 4),
                                   "yahoo": round(y, 4),
                                   "held": t in held})
                    break
            # 2) staleness: yahoo has newer sessions than the cache
            newest_y = max(ys)
            if newest_y > rows[0][0] and (
                    dt.date.fromisoformat(newest_y)
                    - dt.date.fromisoformat(rows[0][0])).days >= 4:
                issues.append({"ticker": t, "kind": "stale_cache",
                               "cache_last": rows[0][0],
                               "yahoo_last": newest_y, "held": t in held})
        # 3) flat-line: identical closes across the window
        closes = [c for _, c in rows]
        if len(closes) == 5 and len(set(closes)) == 1:
            issues.append({"ticker": t, "kind": "flatline",
                           "close": closes[0], "held": t in held})

    # 4) broker truth: T212 live price vs our latest cache close
    try:
        bs = json.load(open(os.path.join(DATA_DIR, "broker_state.json")))
        for p in bs.get("positions", []):
            t = p.get("ticker")
            bp = p.get("current_price")
            rows = cached.get(t)
            if t and bp and rows and rows[0][1] > 0:
                drift = abs(bp - rows[0][1]) / rows[0][1]
                if drift > BROKER_FLAG:
                    issues.append({"ticker": t, "kind": "broker_disagrees",
                                   "broker": bp, "cache": rows[0][1],
                                   "drift_pct": round(drift * 100, 1),
                                   "held": True,
                                   "note": "broker is the account of record"})
    except Exception:
        pass

    held_issues = [i for i in issues if i.get("held")]
    report = {
        "generated": now.isoformat(timespec="seconds"),
        "source": "nightly_audit",
        "tickers_checked": checked,
        "issues": len(issues),
        "held_ticker_issues": len(held_issues),
        "detail": issues[:60],
        "verdict": ("CLEAN — all sources agree" if not issues else
                    "{} discrepancies ({} on HELD tickers) — study session "
                    "must judge whether these tickers' data can be trusted"
                    .format(len(issues), len(held_issues))),
    }
    json.dump(report, open(OUT, "w"), indent=1)
    return report


if __name__ == "__main__":
    r = audit()
    print("data audit:", r.get("tickers_checked", 0), "tickers,",
          r.get("issues", 0), "issues ->", OUT)
    print(r.get("verdict", ""))
    for i in (r.get("detail") or [])[:8]:
        print(" ", i)
