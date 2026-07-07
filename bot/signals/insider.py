"""Insider-buy signal from SEC EDGAR Form 4 filings.

Finds open-market purchases (transaction code P) by directors/officers in the
lookback window, aggregated per ticker. Clustered buying (several insiders)
scores higher than a single purchase.
"""
import json
import os
import time
import datetime as dt
import xml.etree.ElementTree as ET

import requests

from bot.config import CACHE_DIR

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
TICKER_MAP_CACHE = os.path.join(CACHE_DIR, "company_tickers.json")
TICKER_MAP_MAX_AGE_DAYS = 7
SEC_REQUEST_DELAY = 0.12  # stay under SEC's 10 req/s limit


def _session(user_agent):
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent})
    return s


def cik_to_ticker_map(sess):
    """CIK (int) -> ticker, cached locally and refreshed weekly."""
    if os.path.exists(TICKER_MAP_CACHE):
        age = time.time() - os.path.getmtime(TICKER_MAP_CACHE)
        if age < TICKER_MAP_MAX_AGE_DAYS * 86400:
            with open(TICKER_MAP_CACHE) as f:
                raw = json.load(f)
            return {int(v["cik_str"]): v["ticker"] for v in raw.values()}
    r = sess.get(TICKER_MAP_URL, timeout=30)
    r.raise_for_status()
    raw = r.json()
    with open(TICKER_MAP_CACHE, "w") as f:
        json.dump(raw, f)
    return {int(v["cik_str"]): v["ticker"] for v in raw.values()}


def recent_form4_filings(sess, lookback_days, max_pages=10):
    """Yield (issuer_cik, adsh, primary_doc) for recent Form 4 filings."""
    end = dt.date.today()
    start = end - dt.timedelta(days=lookback_days)
    seen = set()
    for page in range(max_pages):
        params = {
            "q": "",
            "forms": "4",
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
            "from": page * 100,
        }
        r = sess.get(FTS_URL, params=params, timeout=30)
        if r.status_code != 200:
            break
        hits = r.json().get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            src = h.get("_source", {})
            adsh = src.get("adsh")
            if not adsh or adsh in seen:
                continue
            seen.add(adsh)
            doc = h.get("_id", "").split(":", 1)[-1] or "primary_doc.xml"
            ciks = [int(c) for c in src.get("ciks", [])]
            yield ciks, adsh, doc
        time.sleep(SEC_REQUEST_DELAY)


def fetch_form4_purchases(sess, issuer_cik, adsh, doc):
    """Parse one Form 4 XML; return (owner_name, total_purchase_usd) for
    open-market buys (code P, acquired). Returns None if no purchase."""
    url = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(
        issuer_cik, adsh.replace("-", ""), doc
    )
    try:
        r = sess.get(url, timeout=30)
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.content)
    except Exception:
        return None

    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or "unknown"
    total = 0.0
    for txn in root.iter("nonDerivativeTransaction"):
        code = txn.findtext(".//transactionCoding/transactionCode")
        acq = txn.findtext(".//transactionAcquiredDisposedCode/value")
        if code != "P" or acq != "A":
            continue
        try:
            shares = float(txn.findtext(".//transactionShares/value") or 0)
            price = float(txn.findtext(".//transactionPricePerShare/value") or 0)
        except (TypeError, ValueError):
            continue
        total += shares * price
    if total <= 0:
        return None
    return owner, total


def scan_insider_buys(cfg, price_filter):
    """Return {ticker: {"total_usd", "n_insiders", "filings"}} for tickers that
    pass price_filter(tickers) -> set of eligible tickers.

    Two passes: first collect candidate tickers cheaply from filing metadata,
    filter by price/liquidity, then download XML only for survivors.
    """
    sess = _session(cfg["edgar_user_agent"])
    cikmap = cik_to_ticker_map(sess)
    lookback = cfg["signals"]["insider_lookback_days"]

    filings_by_ticker = {}
    for ciks, adsh, doc in recent_form4_filings(sess, lookback):
        for cik in ciks:
            ticker = cikmap.get(cik)
            if ticker:
                filings_by_ticker.setdefault(ticker, []).append((cik, adsh, doc))
                break

    eligible = price_filter(list(filings_by_ticker.keys()))

    results = {}
    min_usd = cfg["signals"]["insider_min_purchase_usd"]
    for ticker in eligible:
        owners = {}
        for cik, adsh, doc in filings_by_ticker[ticker]:
            parsed = fetch_form4_purchases(sess, cik, adsh, doc)
            time.sleep(SEC_REQUEST_DELAY)
            if parsed:
                owner, usd = parsed
                owners[owner] = owners.get(owner, 0.0) + usd
        total = sum(owners.values())
        if total >= min_usd:
            results[ticker] = {
                "total_usd": round(total, 2),
                "n_insiders": len(owners),
                "filings": len(filings_by_ticker[ticker]),
            }
    return results


def insider_score(info):
    """0..3 based on size and clustering of purchases."""
    score = 1.0
    if info["total_usd"] >= 100000:
        score += 1.0
    if info["total_usd"] >= 250000:
        score += 0.5
    if info["n_insiders"] >= 2:
        score += 0.5
    return min(score, 3.0)
