"""GBP/USD exchange rate, shared by dashboard display and broker sync.

The Trading 212 account is denominated in GBP; US stocks trade in USD. This is
the single place both sides convert. Yahoo GBPUSD=X, cached 12h, falls back to
the last cached rate, then a hardcoded anchor.
"""
import json
import os
import time

from bot.config import DATA_DIR

CACHE = os.path.join(DATA_DIR, "cache", "fx_gbpusd.json")
FALLBACK_GBP_PER_USD = 0.74


def gbp_per_usd():
    """GBP per 1 USD (e.g. 0.7468). Never raises."""
    try:
        if os.path.exists(CACHE):
            with open(CACHE) as f:
                c = json.load(f)
            if time.time() - c.get("at", 0) < 12 * 3600 and c.get("rate"):
                return float(c["rate"])
            stale = float(c.get("rate") or 0)
        else:
            stale = 0
    except Exception:
        stale = 0
    try:
        from bot import market
        gbpusd = market.last_price("GBPUSD=X")     # USD per £1
        if gbpusd and gbpusd > 0.5:
            rate = round(1.0 / gbpusd, 6)
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w") as f:
                json.dump({"rate": rate, "at": time.time()}, f)
            return rate
    except Exception:
        pass
    return stale or FALLBACK_GBP_PER_USD


def usd_per_gbp():
    return 1.0 / gbp_per_usd()
