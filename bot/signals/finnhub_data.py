"""Optional Finnhub integration (free key from https://finnhub.io/register).

Activates automatically when "finnhub_key" is present in data/secrets.json
(locally) or the FINNHUB_KEY Actions secret (cloud). Without a key every
function returns None and the bot behaves exactly as before.

Free-tier endpoints used:
- /calendar/earnings        — reliable next-earnings date (yfinance is patchy)
- /stock/insider-sentiment  — monthly MSPR: aggregated insider buy/sell tilt
"""
import datetime as dt
import json
import os

import requests

from bot.config import DATA_DIR

BASE = "https://finnhub.io/api/v1"


def _key():
    try:
        with open(os.path.join(DATA_DIR, "secrets.json")) as f:
            return json.load(f).get("finnhub_key") or None
    except Exception:
        return None


def next_earnings_days(ticker):
    """Days until next earnings, or None (no key / no data)."""
    k = _key()
    if not k:
        return None
    today = dt.date.today()
    try:
        r = requests.get(BASE + "/calendar/earnings", params={
            "symbol": ticker, "from": today.isoformat(),
            "to": (today + dt.timedelta(days=100)).isoformat(), "token": k},
            timeout=15)
        if r.status_code != 200:
            return None
        dates = [dt.date.fromisoformat(e["date"])
                 for e in r.json().get("earningsCalendar", []) if e.get("date")]
        future = [d for d in dates if d >= today]
        return (min(future) - today).days if future else None
    except Exception:
        return None


def insider_sentiment_bonus(ticker):
    """-0.3..+0.3 from Finnhub's MSPR (insider buy/sell tilt, last 3 months),
    or None without a key."""
    k = _key()
    if not k:
        return None
    today = dt.date.today()
    try:
        r = requests.get(BASE + "/stock/insider-sentiment", params={
            "symbol": ticker, "from": (today - dt.timedelta(days=90)).isoformat(),
            "to": today.isoformat(), "token": k}, timeout=15)
        if r.status_code != 200:
            return None
        rows = r.json().get("data", [])
        if not rows:
            return None
        mspr = sum(x.get("mspr", 0) for x in rows) / len(rows)  # -100..100
        return round(max(-0.3, min(mspr / 100 * 0.3, 0.3)), 2)
    except Exception:
        return None


def analyst_trend(ticker):
    """-0.4..+0.4 from Finnhub analyst recommendation trend (latest month).
    BIDIRECTIONAL: net buy/strongBuy support entries; net sell/strongSell is a
    bearish tell (used to avoid buys and, via the caller, flag held names).
    None without a key. Free endpoint."""
    k = _key()
    if not k:
        return None
    try:
        r = requests.get(BASE + "/stock/recommendation",
                         params={"symbol": ticker, "token": k}, timeout=15)
        if r.status_code != 200:
            return None
        rows = r.json()
        if not rows:
            return None
        m = rows[0]   # most recent month
        bull = m.get("strongBuy", 0) + m.get("buy", 0)
        bear = m.get("strongSell", 0) + m.get("sell", 0)
        total = bull + bear + m.get("hold", 0)
        if total < 2:   # too few analysts to be meaningful (common for small-caps)
            return 0.0
        net = (bull - bear) / total   # -1..+1
        return round(max(-0.4, min(net * 0.4, 0.4)), 2)
    except Exception:
        return None
