"""Macro regime hardening via FRED (Federal Reserve). Optional — activates when
a free FRED_API_KEY is present (data/secrets.json or env). Without it, returns
neutral and the bot falls back to the Yahoo-based quant regime.

Free key: https://fredaccount.stlouisfed.org/apikeys (instant, no cost).

Signals used (all daily-updated series, so we read once per day, not per scan):
- T10Y2Y : 10y-2y yield curve. Inverted (<0) = recession signal → risk-off tilt.
- BAMLH0A0HYM2 : high-yield credit spread. Widening fast = stress → risk-off.
"""
import datetime as dt
import json
import os

import requests

from bot.config import DATA_DIR, CACHE_DIR

BASE = "https://api.stlouisfed.org/fred/series/observations"
CACHE = os.path.join(CACHE_DIR, "fred_macro.json")
TTL_HOURS = 12


def _key():
    if os.environ.get("FRED_API_KEY"):
        return os.environ["FRED_API_KEY"].strip()
    try:
        with open(os.path.join(DATA_DIR, "secrets.json")) as f:
            return (json.load(f).get("fred_api_key") or "").strip() or None
    except Exception:
        return None


def _series_latest(key, series_id, n=60):
    end = dt.date.today()
    start = end - dt.timedelta(days=n)
    r = requests.get(BASE, params={
        "series_id": series_id, "api_key": key, "file_type": "json",
        "observation_start": start.isoformat(), "sort_order": "asc"}, timeout=20)
    if r.status_code != 200:
        return []
    vals = [float(o["value"]) for o in r.json().get("observations", [])
            if o.get("value") not in (".", "", None)]
    return vals


def macro_signal():
    """(tilt, detail) where tilt is -1..+1 (negative = risk-off pressure), or
    (0, {}) with no key. Cached 12h since FRED series update daily."""
    key = _key()
    if not key:
        return 0.0, {}
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                blob = json.load(f)
            import time
            if time.time() - blob["at"] < TTL_HOURS * 3600:
                return blob["tilt"], blob["detail"]
        except Exception:
            pass
    tilt, detail = 0.0, {}
    try:
        curve = _series_latest(key, "T10Y2Y")
        hy = _series_latest(key, "BAMLH0A0HYM2")
        if curve:
            inverted = curve[-1] < 0
            detail["yield_curve_10y2y"] = round(curve[-1], 2)
            tilt += -0.5 if inverted else 0.25
        if len(hy) >= 20:
            widening = hy[-1] > hy[-20] * 1.1  # spread up >10% in ~month
            detail["hy_credit_spread"] = round(hy[-1], 2)
            tilt += -0.5 if widening else 0.25
        tilt = max(-1.0, min(tilt, 1.0))
    except Exception:
        return 0.0, {}
    try:
        import time
        with open(CACHE, "w") as f:
            json.dump({"at": time.time(), "tilt": tilt, "detail": detail}, f)
    except Exception:
        pass
    return tilt, detail
