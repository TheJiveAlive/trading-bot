"""Macro regime hardening. Works KEYLESS by default:
- Yield curve: US Treasury's own daily par-yield CSV (no key) → 10y-2y spread.
- Credit stress: HYG/LQD ratio via Yahoo (high-yield vs investment-grade).
If a FRED_API_KEY is present it upgrades to the official FRED series
(T10Y2Y + BAMLH0A0HYM2), but nothing depends on it.

Signals (daily series — read once per ~12h, never per scan):
- 10y-2y curve inverted (<0) = recession signal → risk-off tilt.
- Credit stress (HY spread widening / HYG:LQD falling) → risk-off tilt.
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


def _treasury_curve_keyless():
    """10y-2y spread from the Treasury's public daily par-yield CSV (no key)."""
    url = ("https://home.treasury.gov/resource-center/data-chart-center/"
           "interest-rates/daily-treasury-rates.csv/{}/all"
           "?type=daily_treasury_yield_curve&field_tdr_date_value={}&_format=csv"
           ).format(dt.date.today().year, dt.date.today().year)
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return None
    lines = [l for l in r.text.strip().splitlines() if l.strip()]
    head = [h.strip().strip('"') for h in lines[0].split(",")]
    row = [v.strip().strip('"') for v in lines[1].split(",")]   # newest first
    try:
        y10 = float(row[head.index("10 Yr")])
        y2 = float(row[head.index("2 Yr")])
        return round(y10 - y2, 2)
    except (ValueError, IndexError):
        return None


def _credit_proxy_keyless():
    """True if credit is STRESSING: HYG/LQD ratio down >1.5% vs ~a month ago."""
    import yfinance as yf
    h = yf.download("HYG LQD", period="2mo", interval="1d",
                    progress=False, auto_adjust=True)["Close"]
    ratio = (h["HYG"] / h["LQD"]).dropna()
    if len(ratio) < 21:
        return None
    return float(ratio.iloc[-1]) < float(ratio.iloc[-20]) * 0.985


def macro_signal():
    """(tilt, detail) where tilt is -1..+1 (negative = risk-off pressure).
    Keyless by default (Treasury CSV + HYG/LQD); FRED upgrade when keyed.
    Cached 12h since these series update daily."""
    key = _key()
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
        if key:
            # FRED (official series) when a key is present
            curve_series = _series_latest(key, "T10Y2Y")
            spread = curve_series[-1] if curve_series else None
            hy = _series_latest(key, "BAMLH0A0HYM2")
            stressing = (hy[-1] > hy[-20] * 1.1) if len(hy) >= 20 else None
            detail["source"] = "FRED"
            if stressing is not None:
                detail["hy_credit_spread"] = round(hy[-1], 2)
        else:
            # keyless: Treasury daily par yields + HYG/LQD credit proxy
            spread = _treasury_curve_keyless()
            stressing = _credit_proxy_keyless()
            detail["source"] = "Treasury+HYG/LQD (keyless)"
        if spread is not None:
            detail["yield_curve_10y2y"] = round(spread, 2)
            tilt += -0.5 if spread < 0 else 0.25
        if stressing is not None:
            detail["credit_stressing"] = bool(stressing)
            tilt += -0.5 if stressing else 0.25
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
