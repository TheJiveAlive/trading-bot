"""Multi-source news aggregation for the dashboard + news scoring.

Sources (all keyless):
- Google News RSS (fresh, per-ticker search)
- Yahoo Finance news (via yfinance)

Filters out stale items (>21 days) and generic market-wrap junk ("most active
stocks", premarket wraps, etc.) that low-news penny stocks otherwise surface.
Cached 20 min so frequent dashboard refreshes don't refetch.
"""
import datetime as dt
import json
import os
import time
import xml.etree.ElementTree as ET

import requests

from bot.config import CACHE_DIR

CACHE = os.path.join(CACHE_DIR, "news_feed.json")
TTL_MIN = 20
MAX_AGE_DAYS = 21
JUNK = ("most active", "correction:", "premarket", "futures mixed", "market wrap",
        "stocks to watch", "week ahead", "movers", "things to know", "what to watch",
        "market open", "market close", "wall street", "futures rise", "futures fall",
        "dow jones", "s&p 500 today")


def _google_news(ticker):
    url = "https://news.google.com/rss/search?q={}+stock+when:21d&hl=en-US&gl=US&ceid=US:en".format(
        requests.utils.quote("$" + ticker))
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        out = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            src_el = item.find("{*}source") if item.find("source") is None else item.find("source")
            src = (src_el.text if src_el is not None else "") or "Google News"
            when = None
            try:
                when = dt.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
            except Exception:
                pass
            if title:
                out.append({"title": title, "url": link, "src": src, "dt": when})
        return out[:5]
    except Exception:
        return []


def _yahoo_news(ticker):
    from bot import market
    out = []
    for item in market.ticker_news(ticker)[:4]:
        c = item.get("content") or {}
        title = c.get("title") or item.get("title")
        url = ((c.get("clickThroughUrl") or {}).get("url")
               or (c.get("canonicalUrl") or {}).get("url") or "")
        pub = c.get("pubDate") or ""
        when = None
        try:
            when = dt.datetime.fromisoformat(pub.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        if title:
            out.append({"title": title, "url": url,
                        "src": (c.get("provider") or {}).get("displayName") or "Yahoo",
                        "dt": when})
    return out


def _finnhub_news(ticker):
    """Finnhub company news (keyed; [] without a key) — cleaner and often faster
    than the RSS scrape, especially from cloud runners where Google throttles."""
    from bot.signals.finnhub_data import _key
    k = _key()
    if not k:
        return []
    try:
        frm = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
        r = requests.get("https://finnhub.io/api/v1/company-news",
                         params={"symbol": ticker, "from": frm,
                                 "to": dt.date.today().isoformat(), "token": k},
                         timeout=15)
        if r.status_code != 200:
            return []
        out = []
        for item in r.json()[:6]:
            title = (item.get("headline") or "").strip()
            when = None
            try:
                when = dt.datetime.utcfromtimestamp(item.get("datetime") or 0)
            except Exception:
                pass
            if title:
                out.append({"title": title, "url": item.get("url") or "",
                            "src": item.get("source") or "Finnhub", "dt": when})
        return out
    except Exception:
        return []


def _alphai_news(ticker):
    """alphai LLM-scored news adapted to the internal item shape (keyed; [] without)."""
    try:
        from bot.signals.alphai import ticker_news, configured
        if not configured():
            return []
        out = []
        for it in ticker_news(ticker):
            when = None
            try:
                when = dt.datetime.strptime(it.get("when", ""), "%Y-%m-%d %H:%M")
            except Exception:
                pass
            out.append({"title": it["title"], "url": it["url"],
                        "src": "{} · rel {}".format(it["src"], it.get("relevance", "?")),
                        "dt": when})
        return out
    except Exception:
        return []


def _fresh_and_clean(items):
    now = dt.datetime.utcnow()
    keep = []
    for it in items:
        t = (it.get("title") or "").lower()
        if any(j in t for j in JUNK):
            continue
        when = it.get("dt")
        if when and (now - when).days > MAX_AGE_DAYS:
            continue
        keep.append(it)
    return keep


ROLLING = os.path.join(CACHE_DIR, "headlines_rolling.json")
ROLLING_MAX = 60
ROLLING_MAX_AGE_DAYS = 7


def _load_rolling():
    try:
        with open(ROLLING) as f:
            items = json.load(f)
        cutoff = time.time() - ROLLING_MAX_AGE_DAYS * 86400
        return [it for it in items if it.get("seen_at", 0) > cutoff]
    except Exception:
        return []


def _merge_rolling(fresh):
    """Persist headlines across refreshes: newest-first, deduped, capped at
    ROLLING_MAX for ROLLING_MAX_AGE_DAYS — the panel never goes blank just
    because one fetch came up dry."""
    rolling = _load_rolling()
    seen = {(it.get("title") or "")[:60] for it in fresh}
    merged = list(fresh)
    for it in rolling:
        k = (it.get("title") or "")[:60]
        if k not in seen:
            seen.add(k)
            merged.append(it)
    merged = merged[:ROLLING_MAX]
    try:
        with open(ROLLING, "w") as f:
            json.dump(merged, f)
    except Exception:
        pass
    return merged


def collect_headlines(tickers, per_ticker=2, min_items=8):
    """[{ticker,title,url,src,when}] fresh & de-junked, cached 20 min.
    PERSISTENT: fresh headlines merge into a 7-day rolling archive which
    backfills the result, so recent headlines stay on the dashboard even when
    the current fetch returns little (flat book, quiet weekend, source hiccup)."""
    key = ",".join(sorted(set(tickers)))
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                blob = json.load(f)
            if blob.get("key") == key and time.time() - blob["at"] < TTL_MIN * 60:
                return blob["items"]
        except Exception:
            pass
    out, seen = [], set()
    for t in tickers:
        merged = _fresh_and_clean(_google_news(t) + _yahoo_news(t) + _finnhub_news(t)
                                  + _alphai_news(t))
        merged.sort(key=lambda x: x.get("dt") or dt.datetime.min, reverse=True)
        for it in merged[:per_ticker]:
            k = (it["title"] or "")[:60]
            if k in seen:
                continue
            seen.add(k)
            out.append({"ticker": t, "title": it["title"], "url": it["url"],
                        "src": it["src"],
                        "when": it["dt"].strftime("%d %b %H:%M") if it.get("dt") else "",
                        "seen_at": time.time()})
    result = _merge_rolling(out)[:max(min_items, len(out))]
    try:
        with open(CACHE, "w") as f:
            json.dump({"key": key, "at": time.time(), "items": result}, f)
    except Exception:
        pass
    return result
