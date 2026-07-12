"""alphai.io — LLM-scored financial news + per-ticker AI sentiment (keyed).

Free tier is ~100 requests/day with a per-minute burst cap, so this module is
deliberately stingy: per-ticker caches (news 3h, sentiment 6h) and a local
daily budget counter that hard-stops at BUDGET_PER_DAY so a busy scan day can
never exhaust the quota. Everything degrades to empty/0 without a key or when
over budget — the bot never depends on this source.

Auth: Authorization: Bearer <ALPHAI_KEY env or secrets.json 'alphai_key'>.
Docs: https://alphai.io/developers (relevance 1-10; 7-8 = real company news,
9-10 = primary material disclosures).
"""
import datetime as dt
import json
import os
import time

import requests

from bot.config import DATA_DIR, CACHE_DIR

BASE = "https://api.alphai.io"
NEWS_CACHE = os.path.join(CACHE_DIR, "alphai_news.json")
SENT_CACHE = os.path.join(CACHE_DIR, "alphai_sentiment.json")
BUDGET_FILE = os.path.join(CACHE_DIR, "alphai_budget.json")
NEWS_TTL_H = 3
SENT_TTL_H = 6
BUDGET_PER_DAY = 80          # hard stop below the ~100/day free cap


def _key():
    k = os.environ.get("ALPHAI_KEY")
    if k:
        return k.strip()
    try:
        with open(os.path.join(DATA_DIR, "secrets.json")) as f:
            return (json.load(f).get("alphai_key") or "").strip() or None
    except Exception:
        return None


def configured():
    return _key() is not None


def _budget_ok():
    """True if we may spend one more request today; increments the counter."""
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


def _cache_get(path, key, ttl_h):
    try:
        with open(path) as f:
            blob = json.load(f)
        ent = blob.get(key)
        if ent and time.time() - ent.get("at", 0) < ttl_h * 3600:
            return ent.get("data")
    except Exception:
        pass
    return None


def _cache_put(path, key, data):
    blob = {}
    try:
        with open(path) as f:
            blob = json.load(f)
    except Exception:
        pass
    blob[key] = {"at": time.time(), "data": data}
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(blob, f)
    except Exception:
        pass


def _get(path, params=None):
    if not configured() or not _budget_ok():
        return None
    try:
        r = requests.get(BASE + path, params=params or {}, timeout=15,
                         headers={"Authorization": "Bearer " + _key(),
                                  "User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def ticker_news(ticker, min_relevance=6):
    """[{title,url,src,when,relevance,sentiment}] for one ticker, cached 3h.
    min_relevance 6 keeps 'minor-but-real company news' and better."""
    ticker = (ticker or "").upper()
    cached = _cache_get(NEWS_CACHE, ticker, NEWS_TTL_H)
    if cached is not None:
        return cached
    data = _get("/api/news/", {"symbol": ticker, "min_relevance": min_relevance,
                               "collapse": "story"})
    items = []
    for a in (data or {}).get("results", [])[:6]:
        enrich = a.get("enrichment") or {}
        sent = ""
        for ta in ((enrich.get("ai_trading_insights") or {}).get("ticker_analysis") or []):
            if (ta.get("ticker") or "").upper() == ticker:
                sent = ((ta.get("impact_analysis") or {}).get("sentiment") or "")
        items.append({
            "title": a.get("title") or "",
            "url": a.get("url") or a.get("link") or a.get("article_url") or "",
            "src": a.get("source") or a.get("domain") or "alphai",
            "when": (a.get("published_at") or a.get("published") or "")[:16].replace("T", " "),
            "relevance": enrich.get("relevance_score"),
            "sentiment": sent,
        })
    if data is not None:
        _cache_put(NEWS_CACHE, ticker, items)
    return items


def sentiment_bonus(ticker):
    """-0.5..+0.5 from the 7-day AI sentiment rollup (bullish vs bearish
    article counts). Bidirectional: negative consensus subtracts. 0 when
    keyless/over-budget/no data."""
    ticker = (ticker or "").upper()
    cached = _cache_get(SENT_CACHE, ticker, SENT_TTL_H)
    if cached is not None:
        return cached
    data = _get("/api/symbols/{}/sentiment-summary/".format(ticker))
    bonus = 0.0
    if data:
        bull = float(data.get("bullish", 0) or 0)
        bear = float(data.get("bearish", 0) or 0)
        total = bull + bear
        if total >= 2:                       # demand at least 2 opinionated articles
            bonus = round(max(-0.5, min(0.5, (bull - bear) / total * 0.5)), 2)
    if data is not None:
        _cache_put(SENT_CACHE, ticker, bonus)
    return bonus


def health():
    """(ok, detail) for healthcheck — costs 1 request when keyed."""
    if not configured():
        return (True, "no key set (optional) — alphai disabled")
    data = _get("/api/news/", {"min_relevance": 8})
    if data is None:
        return (False, "alphai unreachable / 4xx / over budget")
    n = len(data.get("results", []))
    return (True, "alphai OK — {} high-relevance stories in feed".format(n))
