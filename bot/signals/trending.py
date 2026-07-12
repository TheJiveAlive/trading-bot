"""Trending-ticker buzz — free, keyless second social/attention source
alongside ApeWisdom (Reddit).

Sources, in order:
- Stocktwits trending (tried first; currently Cloudflare-gated for scripts,
  kept in case it reopens)
- Yahoo Finance trending US (reliable, keyless)

A name trending here AND buzzing on Reddit is confirmed multi-platform
attention. Small additive bonus only — the pump-risk veto in confluence still
applies, so attention can never push a pump past the gate on its own.
"""
import json
import os
import re
import time

import requests

from bot.config import CACHE_DIR

CACHE = os.path.join(CACHE_DIR, "trending_symbols.json")
TTL_MIN = 15
_PLAIN = re.compile(r"^[A-Z]{1,5}$")   # drop crypto (BTC-USD), futures (CL=F), foreign


def _stocktwits():
    try:
        r = requests.get("https://api.stocktwits.com/api/2/trending/symbols.json",
                         timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return {}
        return {(s.get("symbol") or "").upper(): i + 1
                for i, s in enumerate(r.json().get("symbols", []))}
    except Exception:
        return {}


def _yahoo_trending():
    try:
        r = requests.get("https://query1.finance.yahoo.com/v1/finance/trending/US",
                         params={"count": 30}, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return {}
        quotes = r.json()["finance"]["result"][0]["quotes"]
        return {(q.get("symbol") or "").upper(): i + 1 for i, q in enumerate(quotes)}
    except Exception:
        return {}


def trending_symbols():
    """{SYMBOL: rank} (rank 1 = hottest), plain US equities only, cached 15 min.
    Empty dict on failure — the bot must never depend on this source."""
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                blob = json.load(f)
            if time.time() - blob.get("at", 0) < TTL_MIN * 60:
                return blob.get("symbols", {})
        except Exception:
            pass
    raw = _stocktwits() or _yahoo_trending()
    symbols = {s: r for s, r in raw.items() if _PLAIN.match(s)}
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump({"at": time.time(), "symbols": symbols}, f)
    except Exception:
        pass
    return symbols


def trending_score(ticker, trending=None):
    """0..1: 1.0 for top-10 trending, 0.5 for the rest, 0 if absent."""
    trending = trending if trending is not None else trending_symbols()
    rank = trending.get((ticker or "").upper())
    if not rank:
        return 0.0
    return 1.0 if rank <= 10 else 0.5
