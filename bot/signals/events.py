"""Extra decision signals (all free):

- SEC 8-K material events: an 8-K is filed for major events (M&A, big contracts,
  management change, delisting notices). A very recent 8-K = something happened;
  worth a catalyst flag and a nudge for the research layer to investigate.
- Short interest (Nasdaq): days-to-cover. High = short-squeeze fuel (a tailwind
  for a name already moving up) but also crowded-short risk. Used as a small
  contextual score, never a standalone thesis.
"""
import datetime as dt
import json
import os
import time

import requests

from bot.config import CACHE_DIR
from bot.signals.dilution import _ticker_to_cik

FTS = "https://efts.sec.gov/LATEST/search-index"
NASDAQ = "https://api.nasdaq.com/api/quote/{}/short-interest?assetClass=stocks"
CACHE = os.path.join(CACHE_DIR, "events.json")
TTL_H = 8


def _cache_get(key):
    if os.path.exists(CACHE):
        try:
            blob = json.load(open(CACHE))
            hit = blob.get(key)
            if hit and time.time() - hit["at"] < TTL_H * 3600:
                return hit["val"]
        except Exception:
            pass
    return None


def _cache_put(key, val):
    blob = {}
    if os.path.exists(CACHE):
        try:
            blob = json.load(open(CACHE))
        except Exception:
            blob = {}
    blob[key] = {"at": time.time(), "val": val}
    try:
        json.dump(blob, open(CACHE, "w"))
    except Exception:
        pass


def recent_8k(cfg, ticker, days=7):
    """Days since the most recent 8-K (material event), or None."""
    ck = "8k:" + ticker
    c = _cache_get(ck)
    if c is not None:
        return c.get("days_since")
    cik = _ticker_to_cik().get(ticker.upper())
    out = {"days_since": None}
    if cik:
        try:
            end = dt.date.today(); start = end - dt.timedelta(days=days)
            r = requests.get(FTS, params={"q": "", "forms": "8-K", "ciks": cik,
                             "dateRange": "custom", "startdt": start.isoformat(),
                             "enddt": end.isoformat()},
                             headers={"User-Agent": cfg["edgar_user_agent"]}, timeout=15)
            if r.status_code == 200:
                dates = [h["_source"].get("file_date") for h in
                         r.json().get("hits", {}).get("hits", []) if h.get("_source")]
                if dates:
                    last = max(dt.date.fromisoformat(d) for d in dates)
                    out["days_since"] = (end - last).days
        except Exception:
            pass
    _cache_put(ck, out)
    return out["days_since"]


def short_interest(ticker):
    """{'days_to_cover': float, 'interest': int} or {} — from Nasdaq (free)."""
    ck = "si:" + ticker
    c = _cache_get(ck)
    if c is not None:
        return c
    out = {}
    try:
        r = requests.get(NASDAQ.format(ticker.upper()),
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                         timeout=15)
        if r.status_code == 200:
            rows = ((r.json().get("data") or {}).get("shortInterestTable") or {}).get("rows") or []
            if rows:
                row = rows[0]
                out = {"days_to_cover": float(row.get("daysToCover") or 0),
                       "interest": int((row.get("interest") or "0").replace(",", "")),
                       "as_of": row.get("settlementDate")}
    except Exception:
        pass
    _cache_put(ck, out)
    return out


def event_score(cfg, ticker):
    """0..0.8 contextual bonus: fresh 8-K + squeeze fuel. (detail dict too.)"""
    score = 0.0
    detail = {}
    d8k = recent_8k(cfg, ticker)
    if d8k is not None:
        detail["8k_days_ago"] = d8k
        if d8k <= 3:
            score += 0.4    # very fresh material event
        elif d8k <= 7:
            score += 0.2
    si = short_interest(ticker)
    if si.get("days_to_cover"):
        detail["days_to_cover"] = round(si["days_to_cover"], 1)
        if si["days_to_cover"] >= 5:
            score += 0.4    # heavy short interest = squeeze fuel
        elif si["days_to_cover"] >= 3:
            score += 0.2
    return round(min(score, 0.8), 2), detail
