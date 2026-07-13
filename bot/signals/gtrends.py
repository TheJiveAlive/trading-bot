"""Google Trends retail-attention signal (keyless, via pytrends).

Measures whether SEARCH interest in a ticker is accelerating — a third,
independent attention source next to Reddit (ApeWisdom) and Yahoo trending.
Rising search interest that precedes price often marks early retail discovery;
already-peaked interest is worth nothing (or worse).

Deliberately defensive: Google throttles aggressively, so results are cached
6h per ticker, failures return 0, and a per-day request budget hard-stops.
The bot must never depend on this source.
"""
import datetime as dt
import json
import os
import time

from bot.config import CACHE_DIR

CACHE = os.path.join(CACHE_DIR, "gtrends.json")
BUDGET_FILE = os.path.join(CACHE_DIR, "gtrends_budget.json")
TTL_H = 6
BUDGET_PER_DAY = 40


def _budget_ok():
    today = dt.date.today().isoformat()
    used = 0
    try:
        with open(BUDGET_FILE) as f:
            b = json.load(f)
        if b.get("day") == today:
            used = int(b.get("used", 0))
    except Exception:
        pass
    if used >= BUDGET_PER_DAY:
        return False
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(BUDGET_FILE, "w") as f:
            json.dump({"day": today, "used": used + 1}, f)
    except Exception:
        pass
    return True


def trends_score(ticker):
    """0..1: how sharply Google search interest is RISING for '<ticker> stock'.
    1.0 = last-3-day average >= 2x the prior-week average (fresh discovery);
    0.5 = >= 1.4x; 0 = flat/falling/unknown. Cached 6h; fail-silent."""
    ticker = (ticker or "").upper()
    blob = {}
    try:
        with open(CACHE) as f:
            blob = json.load(f)
        ent = blob.get(ticker)
        if ent and time.time() - ent.get("at", 0) < TTL_H * 3600:
            return ent.get("score", 0.0)
    except Exception:
        blob = {}
    if not _budget_ok():
        return 0.0
    score = 0.0
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(5, 12))
        pt.build_payload(["{} stock".format(ticker)], timeframe="now 7-d", geo="US")
        df = pt.interest_over_time()
        if df is not None and len(df) > 24:
            col = df.columns[0]
            vals = df[col].astype(float).values
            recent = vals[-int(len(vals) * 0.4):].mean()      # ~last 3 days
            base = vals[:int(len(vals) * 0.6)].mean() or 1.0  # prior stretch
            ratio = recent / base if base else 0
            score = 1.0 if ratio >= 2.0 else (0.5 if ratio >= 1.4 else 0.0)
    except Exception:
        score = 0.0
    try:
        blob[ticker] = {"at": time.time(), "score": score}
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump(blob, f)
    except Exception:
        pass
    return score
