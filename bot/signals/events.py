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


USASPEND = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


def gov_contract(company_name, days=45):
    """Recent federal contract awards to this company (the 'US influence/gov
    spending' money-flow catalyst). Returns {'total_usd', 'days_since'} or {}.
    Matches by recipient name — fuzzy, so treat as a soft catalyst, not a veto."""
    if not company_name or len(company_name) < 4:
        return {}
    ck = "gov:" + company_name.upper()[:24]
    c = _cache_get(ck)
    if c is not None:
        return c
    out = {}
    try:
        import datetime as dt
        end = dt.date.today(); start = end - dt.timedelta(days=days)
        # first distinctive word of the name (drops Inc/Corp/etc via caller)
        term = company_name.split()[0]
        r = requests.post(USASPEND, timeout=20, headers={"Content-Type": "application/json"},
                          json={"filters": {"award_type_codes": ["A", "B", "C", "D"],
                                "recipient_search_text": [term],
                                "time_period": [{"start_date": start.isoformat(),
                                                 "end_date": end.isoformat()}]},
                                "fields": ["Recipient Name", "Award Amount", "Start Date"],
                                "limit": 5, "sort": "Award Amount", "order": "desc"})
        if r.status_code == 200:
            res = r.json().get("results", [])
            # require the recipient name to actually contain our term (avoid noise)
            match = [x for x in res if term.upper() in (x.get("Recipient Name") or "").upper()]
            if match:
                total = sum(float(x.get("Award Amount") or 0) for x in match)
                if total >= 1_000_000:  # ignore trivial awards
                    out = {"total_usd": total, "n": len(match)}
    except Exception:
        pass
    _cache_put(ck, out)
    return out


def insider_selling(cfg, ticker, days=10):
    """Total open-market insider SELL $ (Form 4 code S) in the lookback — the
    mirror of the core insider-BUY signal. Cluster selling is a bearish tell:
    used to avoid new buys AND to flag held positions for exit. Cached 8h."""
    import datetime as dt
    import xml.etree.ElementTree as ET
    ck = "isell:" + ticker
    c = _cache_get(ck)
    if c is not None:
        return c
    out = {"total_usd": 0.0, "n": 0}
    cik = _ticker_to_cik().get(ticker.upper())
    if cik:
        try:
            end = dt.date.today(); start = end - dt.timedelta(days=days)
            r = requests.get(FTS, params={"q": "", "forms": "4", "ciks": cik,
                             "dateRange": "custom", "startdt": start.isoformat(),
                             "enddt": end.isoformat()},
                             headers={"User-Agent": cfg["edgar_user_agent"]}, timeout=15)
            if r.status_code == 200:
                hits = r.json().get("hits", {}).get("hits", [])[:4]
                for h in hits:
                    src = h.get("_source", {})
                    adsh = src.get("adsh", "")
                    doc = h.get("_id", "").split(":", 1)[-1] or "primary_doc.xml"
                    ic = int((src.get("ciks") or [cik])[0])
                    url = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(
                        ic, adsh.replace("-", ""), doc)
                    try:
                        rr = requests.get(url, headers={"User-Agent": cfg["edgar_user_agent"]}, timeout=15)
                        root = ET.fromstring(rr.content)
                        for txn in root.iter("nonDerivativeTransaction"):
                            if (txn.findtext(".//transactionCoding/transactionCode") == "S"
                                    and txn.findtext(".//transactionAcquiredDisposedCode/value") == "D"):
                                sh = float(txn.findtext(".//transactionShares/value") or 0)
                                px = float(txn.findtext(".//transactionPricePerShare/value") or 0)
                                out["total_usd"] += sh * px
                        if out["total_usd"] > 0:
                            out["n"] += 1
                    except Exception:
                        continue
        except Exception:
            pass
    _cache_put(ck, out)
    return out


def event_score(cfg, ticker, company_name=None):
    """0..1.2 contextual bonus: fresh 8-K + squeeze fuel + federal contract."""
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
    if company_name:
        gc = gov_contract(company_name)
        if gc.get("total_usd"):
            detail["gov_contract_usd"] = int(gc["total_usd"])
            score += 0.4    # recent federal contract = real catalyst
    return round(min(score, 1.2), 2), detail
