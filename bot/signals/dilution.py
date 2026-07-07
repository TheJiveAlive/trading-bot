"""Dilution early-warning from EDGAR: S-3 shelf registrations and 424B
offering prospectuses. For sub-$20 companies these are the classic prelude to
a dilutive raise that craters the price — a fresh 424B is a hard veto.
"""
import datetime as dt
import json
import os
import time

import requests

from bot.config import CACHE_DIR

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
OFFERING_FORMS = "424B1,424B2,424B3,424B4,424B5,S-1,S-3,F-1,F-3"
LOOKBACK_DAYS = 90
HARD_VETO_DAYS = 30
CACHE_PATH = os.path.join(CACHE_DIR, "dilution_checks.json")
CACHE_TTL_HOURS = 12


def _ticker_to_cik():
    """ticker -> zero-padded CIK from the cached SEC company map."""
    path = os.path.join(CACHE_DIR, "company_tickers.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}


def check_dilution(cfg, ticker):
    """{'recent_filings': n, 'days_since_last': d|None, 'veto': bool}.
    Cached for 12h per ticker to spare EDGAR."""
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)
    hit = cache.get(ticker)
    if hit and time.time() - hit["at"] < CACHE_TTL_HOURS * 3600:
        return hit["result"]

    result = {"recent_filings": 0, "days_since_last": None, "veto": False,
              "alltime_filings": 0, "chronic": False}
    cik = _ticker_to_cik().get(ticker.upper())
    if cik:
        end = dt.date.today()
        start = end - dt.timedelta(days=LOOKBACK_DAYS)
        headers = {"User-Agent": cfg["edgar_user_agent"]}
        try:
            r = requests.get(FTS_URL, params={
                "q": "", "forms": OFFERING_FORMS, "ciks": cik,
                "dateRange": "custom", "startdt": start.isoformat(),
                "enddt": end.isoformat()}, headers=headers, timeout=20)
            if r.status_code == 200:
                hits = r.json().get("hits", {}).get("hits", [])
                dates = [h["_source"].get("file_date") for h in hits
                         if h.get("_source", {}).get("file_date")]
                result["recent_filings"] = len(dates)
                if dates:
                    last = max(dt.date.fromisoformat(d) for d in dates)
                    result["days_since_last"] = (end - last).days
                    result["veto"] = result["days_since_last"] <= HARD_VETO_DAYS
            # lifetime offering count: the serial-diluter fingerprint
            r2 = requests.get(FTS_URL, params={
                "q": "", "forms": OFFERING_FORMS, "ciks": cik},
                headers=headers, timeout=20)
            if r2.status_code == 200:
                result["alltime_filings"] = (r2.json().get("hits", {})
                                             .get("total", {}).get("value", 0))
                result["chronic"] = result["alltime_filings"] >= 15
        except Exception:
            pass  # EDGAR down != block trading; fail open, log nothing found

    cache[ticker] = {"at": time.time(), "result": result}
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)
    return result
