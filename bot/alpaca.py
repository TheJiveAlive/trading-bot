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


def historical_bars(tickers, start, end, timeframe="1Day"):
    """{ticker: DataFrame[Close, Volume]} of daily bars from Alpaca, matching
    the Yahoo shape used by the backtester. Much faster + no throttling vs
    Yahoo's bulk download. Handles pagination. Returns {} if unconfigured."""
    import pandas as pd
    if not configured() or not tickers:
        return {}
    out = {}
    # Alpaca allows many symbols per request; chunk to keep URLs sane
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        page_token = None
        rows = {t: [] for t in chunk}
        while True:
            params = {"symbols": ",".join(chunk), "timeframe": timeframe,
                      "start": start, "end": end, "feed": "iex", "limit": 10000}
            if page_token:
                params["page_token"] = page_token
            try:
                r = requests.get(DATA_BASE + "/stocks/bars", params=params,
                                 headers=_headers(), timeout=40)
                if r.status_code != 200:
                    break
                data = r.json()
                for t, bars in (data.get("bars") or {}).items():
                    for b in bars:
                        rows.setdefault(t, []).append((b["t"][:10], b["c"], b["v"]))
                page_token = data.get("next_page_token")
                if not page_token:
                    break
            except Exception:
                break
        for t, rec in rows.items():
            if len(rec) >= 25:
                df = pd.DataFrame(rec, columns=["date", "Close", "Volume"])
                df["date"] = pd.to_datetime(df["date"])
                out[t] = df.set_index("date")[["Close", "Volume"]]
    return out


def latest_quote(ticker):
    """(bid, ask) from Alpaca IEX, or (None, None). Real bid/ask fixes the
    stale-spread false vetoes that Yahoo's .info bid/ask causes."""
    if not configured():
        return (None, None)
    try:
        r = requests.get(DATA_BASE + "/stocks/quotes/latest",
                         params={"symbols": ticker, "feed": "iex"},
                         headers=_headers(), timeout=15)
        if r.status_code != 200:
            return (None, None)
        q = (r.json().get("quotes") or {}).get(ticker) or {}
        bid, ask = q.get("bp"), q.get("ap")
        return (float(bid) if bid else None, float(ask) if ask else None)
    except Exception:
        return (None, None)


def health():
    if not configured():
        return (True, "no Alpaca key (optional) — using Yahoo for quotes")
    px = latest_prices(["AAPL"])
    return (bool(px), "Alpaca IEX feed live (AAPL ${})".format(px.get("AAPL", "?"))
            if px else "Alpaca keys set but no data returned")
