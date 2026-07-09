"""Alpaca market-data hook (optional). Activates when ALPACA_KEY + ALPACA_SECRET
are present (data/secrets.json or env). Free account: https://alpaca.markets

Used as the preferred real-time quote source (IEX feed on the free tier), with
Yahoo as the fallback everywhere. Keys are read locally/from GitHub secrets and
never exposed to the browser — the live dashboard reads a pre-computed
prices.json, not Alpaca directly.
"""
import json
import os

import requests

from bot.config import DATA_DIR

DATA_BASE = "https://data.alpaca.markets/v2"


def _creds():
    k = os.environ.get("ALPACA_KEY")
    s = os.environ.get("ALPACA_SECRET")
    if k and s:
        return k.strip(), s.strip()
    try:
        with open(os.path.join(DATA_DIR, "secrets.json")) as f:
            d = json.load(f)
        k, s = (d.get("alpaca_key") or "").strip(), (d.get("alpaca_secret") or "").strip()
        return (k, s) if k and s else (None, None)
    except Exception:
        return None, None


def configured():
    return all(_creds())


def _headers():
    k, s = _creds()
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}


def latest_prices(tickers):
    """{ticker: price} via Alpaca's batch latest-trades endpoint, or {} if
    unconfigured/failed. One call for many symbols — very quota-efficient."""
    if not tickers or not configured():
        return {}
    out = {}
    try:
        r = requests.get(DATA_BASE + "/stocks/trades/latest",
                         params={"symbols": ",".join(tickers), "feed": "iex"},
                         headers=_headers(), timeout=20)
        if r.status_code != 200:
            return {}
        for t, trade in (r.json().get("trades") or {}).items():
            p = trade.get("p")
            if p:
                out[t] = float(p)
    except Exception:
        return {}
    return out


def health():
    if not configured():
        return (True, "no Alpaca key (optional) — using Yahoo for quotes")
    px = latest_prices(["AAPL"])
    return (bool(px), "Alpaca IEX feed live (AAPL ${})".format(px.get("AAPL", "?"))
            if px else "Alpaca keys set but no data returned")
