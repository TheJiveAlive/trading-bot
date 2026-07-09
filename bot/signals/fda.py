"""Keyless biotech catalyst check via openFDA (no API key required).

Many small-caps are clinical-stage biotech, where an FDA action (approval,
priority review, complete response letter) is the dominant price catalyst.
This flags a ticker's company if openFDA shows recent drug-submission activity
by a matching sponsor.

Matching is fuzzy (openFDA keys on sponsor company name, not ticker), so this
is used as a soft *positive catalyst hint* and a research flag — never a hard
buy/veto on its own.
"""
import datetime as dt
import json
import os
import time

import requests

from bot.config import CACHE_DIR

URL = "https://api.fda.gov/drug/drugsfda.json"
CACHE = os.path.join(CACHE_DIR, "fda_catalysts.json")
TTL_HOURS = 24


def _company_key(name):
    """Normalise a company name to its distinctive first word for matching."""
    if not name:
        return ""
    junk = {"inc", "corp", "corporation", "ltd", "plc", "co", "the",
            "pharmaceuticals", "pharma", "therapeutics", "bio", "biosciences",
            "holdings", "group", "sa", "nv", "ag"}
    words = [w.strip(",.").lower() for w in name.split()]
    words = [w for w in words if w and w not in junk]
    return words[0] if words else ""


def recent_fda_activity(company_name, days=45):
    """Return a short catalyst note if the sponsor has recent FDA submissions,
    else None. Cached 24h per company key."""
    ck = _company_key(company_name)
    if len(ck) < 3:
        return None
    cache = {}
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    hit = cache.get(ck)
    if hit and time.time() - hit["at"] < TTL_HOURS * 3600:
        return hit["note"]

    note = None
    try:
        since = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
        today = dt.date.today().strftime("%Y%m%d")
        r = requests.get(URL, params={
            "search": 'sponsor_name:"{}"+AND+submissions.submission_status_date:[{}+TO+{}]'.format(
                ck, since, today),
            "limit": 3}, timeout=15)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                sub = results[0].get("submissions", [{}])
                latest = sub[-1] if sub else {}
                note = "openFDA: recent drug submission activity ({})".format(
                    latest.get("submission_status", "filed"))
    except Exception:
        note = None

    cache[ck] = {"at": time.time(), "note": note}
    try:
        with open(CACHE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass
    return note
