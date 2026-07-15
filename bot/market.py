"""Market data helpers built on yfinance, with batch price/volume filtering."""
import math
import warnings

warnings.filterwarnings("ignore")

import yfinance as yf

SECTOR_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def batch_price_volume(tickers, period="1mo"):
    """{ticker: (last_close, avg_dollar_volume)} for tickers with data."""
    out = {}
    if not tickers:
        return out
    for chunk_start in range(0, len(tickers), 200):
        chunk = tickers[chunk_start:chunk_start + 200]
        df = yf.download(chunk, period=period, interval="1d",
                         progress=False, group_by="ticker", threads=True,
                         auto_adjust=True)
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                sub = df[t] if len(chunk) > 1 else df
                closes = sub["Close"].dropna()
                vols = sub["Volume"].dropna()
                if closes.empty or vols.empty:
                    continue
                last = float(closes.iloc[-1])
                adv = float((closes * vols).mean())
                if math.isnan(last) or math.isnan(adv):
                    continue
                out[t] = (last, adv)
            except Exception:
                continue
    return out


def make_universe_filter(cfg):
    """Returns (filter_fn, snapshot dict). filter_fn(tickers) -> eligible set,
    populating snapshot with price/volume for later use."""
    u = cfg["universe"]
    snapshot = {}

    def _filter(tickers):
        data = batch_price_volume(tickers)
        eligible = set()
        for t, (price, adv) in data.items():
            snapshot[t] = {"price": price, "avg_dollar_volume": adv}
            if u["price_min"] <= price <= u["price_max"] and adv >= u["min_avg_dollar_volume"]:
                eligible.add(t)
        return eligible

    return _filter, snapshot


def _broker_held_price(ticker, max_age_min=45):
    """current_price from the broker-of-record snapshot (broker_state.json)
    for a HELD name, or None. Only trusted while the snapshot's own
    'generated' stamp is fresh — file mtime lies after git checkouts."""
    import datetime as dt, json, os
    try:
        from bot.broker_sync import BROKER_STATE
        with open(BROKER_STATE) as f:
            s = json.load(f)
        gen = dt.datetime.fromisoformat(s["generated"].replace("Z", "+00:00"))
        if (dt.datetime.now(dt.timezone.utc) - gen).total_seconds() > max_age_min * 60:
            return None
        for p in s.get("positions") or []:
            if p.get("ticker") == ticker and p.get("current_price"):
                return float(p["current_price"])
    except Exception:
        pass
    return None


def last_price(ticker):
    # prefer Alpaca IEX when configured (real-time, no Yahoo throttling)
    try:
        from bot import alpaca
        if alpaca.configured():
            px = alpaca.latest_prices([ticker])
            if px.get(ticker):
                return px[ticker]
    except Exception:
        pass
    # held names: the broker's own positions quote beats Yahoo — on thin
    # tickers Yahoo's last daily close can run a week stale (2026-07-15:
    # WRAP Yahoo 1.555 from Jul-8 vs broker 2.15) and a stop-check against
    # that stale print would phantom-sell a winner at a fake loss.
    bp = _broker_held_price(ticker)
    if bp is not None:
        return bp
    try:
        h = yf.Ticker(ticker).history(period="5d")
        if h is None or h.empty:
            return None
        closes = h["Close"].dropna()
        # staleness gate: if Yahoo's newest bar is >4 days old, the print is
        # unusable for exit checks — better NO price (caller skips the check)
        # than a phantom stop-out on a week-old close.
        import datetime as dt
        last_ts = closes.index[-1].to_pydatetime()
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=dt.timezone.utc)
        if (dt.datetime.now(dt.timezone.utc) - last_ts).days > 4:
            return None
        return float(closes.iloc[-1])
    except Exception:
        return None


def _cache_path(name):
    import os
    from bot.config import CACHE_DIR
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def price_series(ticker, period="1mo", ttl_min=30):
    """List of daily closes for a sparkline, cached ttl_min minutes so frequent
    dashboard refreshes don't re-hit Yahoo for slow-changing daily bars."""
    import json, os, time
    cache = _cache_path("sparklines.json")
    data = {}
    if os.path.exists(cache):
        try:
            with open(cache) as f:
                data = json.load(f)
        except Exception:
            data = {}
    hit = data.get(ticker)
    if hit and time.time() - hit["at"] < ttl_min * 60:
        return hit["series"]
    try:
        h = yf.Ticker(ticker).history(period=period)
        series = [] if h is None or h.empty else [float(x) for x in h["Close"].dropna().tolist()]
    except Exception:
        series = hit["series"] if hit else []
    data[ticker] = {"at": time.time(), "series": series}
    try:
        with open(cache, "w") as f:
            json.dump(data, f)
    except Exception:
        pass
    return series


def ticker_info(ticker, ttl_min=360):
    """Yahoo info dict, disk-cached 6h (sector/fundamentals don't move intraday)."""
    import json, os, time
    cache = _cache_path("ticker_info.json")
    data = {}
    if os.path.exists(cache):
        try:
            data = json.load(open(cache))
        except Exception:
            data = {}
    hit = data.get(ticker)
    if hit and time.time() - hit["at"] < ttl_min * 60:
        return hit["info"]
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = hit["info"] if hit else {}
    # keep only the fields the bot uses — the full info dict is huge
    keep = {k: info.get(k) for k in (
        "sector", "shortName", "revenueGrowth", "earningsGrowth", "profitMargins",
        "bid", "ask", "regularMarketChangePercent", "52WeekChange") if k in info}
    data[ticker] = {"at": time.time(), "info": keep}
    try:
        json.dump(data, open(cache, "w"))
    except Exception:
        pass
    return keep


def ticker_news(ticker):
    try:
        return yf.Ticker(ticker).news or []
    except Exception:
        return []
