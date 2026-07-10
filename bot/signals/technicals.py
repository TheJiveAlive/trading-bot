"""Intraday technicals and options flow for the confluence entry gate.

Each metric is computed defensively: Yahoo data can be missing or stale,
especially for small caps. Unknown values become None and are excluded from
the confluence vote rather than counted as failures — except hard vetoes
(punishing spread, extreme IV), which block the trade outright.
"""
import datetime as dt
import warnings

warnings.filterwarnings("ignore")

import yfinance as yf

from bot.signals.reddit import pump_risk


def days_to_earnings(ticker, _cache={}):
    """Days until next earnings report, or None if unknown/not scheduled.
    Prefers Finnhub (reliable) when a key is configured; falls back to Yahoo.
    Cached 6h on disk (dates don't move intraday)."""
    import json as _json, os as _os, time as _time
    from bot.config import CACHE_DIR
    path = _os.path.join(CACHE_DIR, "earnings_dates.json")
    disk = {}
    if _os.path.exists(path):
        try:
            disk = _json.load(open(path))
        except Exception:
            disk = {}
    hit = disk.get(ticker)
    if hit and _time.time() - hit["at"] < 6 * 3600:
        return hit["days"]

    def _save(days):
        disk[ticker] = {"at": _time.time(), "days": days}
        try:
            _os.makedirs(CACHE_DIR, exist_ok=True)
            _json.dump(disk, open(path, "w"))
        except Exception:
            pass
        return days

    from bot.signals.finnhub_data import next_earnings_days
    fh = next_earnings_days(ticker)
    if fh is not None:
        return _save(fh)
    try:
        cal = yf.Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            nxt = min(d for d in dates if d >= dt.date.today())
            return _save((nxt - dt.date.today()).days)
    except Exception:
        pass
    return _save(None)


def _intraday(tkr):
    h = tkr.history(period="5d", interval="5m")
    return None if h is None or h.empty else h


def _daily(tkr):
    h = tkr.history(period="3mo", interval="1d")
    return None if h is None or h.empty else h


def compute_metrics(ticker):
    """Return dict of metrics; individual keys are None when unavailable."""
    m = {"rvol": None, "above_vwap": None, "ret5d_pct": None,
         "above_ma20": None, "extension_pct": None, "day_range_pos": None,
         "spread_pct": None, "atm_iv": None, "call_put_ratio": None,
         "last": None}
    tkr = yf.Ticker(ticker)

    intra = _intraday(tkr)
    if intra is not None:
        days = intra.groupby(intra.index.date)
        dates = sorted(days.groups.keys())
        today = days.get_group(dates[-1])
        if len(today) >= 3:
            last = float(today["Close"].iloc[-1])
            m["last"] = last
            tp = (today["High"] + today["Low"] + today["Close"]) / 3
            vol_sum = float(today["Volume"].sum())
            if vol_sum > 0:
                vwap = float((tp * today["Volume"]).sum() / vol_sum)
                m["above_vwap"] = last >= vwap
            # time-adjusted relative volume: today's cumulative volume vs the
            # same number of bars on prior days
            n = len(today)
            prior = [float(days.get_group(d)["Volume"].iloc[:n].sum())
                     for d in dates[:-1]]
            prior = [p for p in prior if p > 0]
            if prior and vol_sum > 0:
                m["rvol"] = round(vol_sum / (sum(prior) / len(prior)), 2)
            hi, lo = float(today["High"].max()), float(today["Low"].min())
            if hi > lo:
                m["day_range_pos"] = round((last - lo) / (hi - lo), 2)

    daily = _daily(tkr)
    if daily is not None and len(daily) >= 21:
        closes = daily["Close"].dropna()
        last = float(closes.iloc[-1])
        m["last"] = m["last"] or last
        if len(closes) >= 6:
            m["ret5d_pct"] = round((last / float(closes.iloc[-6]) - 1) * 100, 1)
        ma20 = float(closes.iloc[-20:].mean())
        m["above_ma20"] = last > ma20
        m["extension_pct"] = round((last / ma20 - 1) * 100, 1)

    # real bid/ask from Alpaca IEX when available (fixes Yahoo's stale .info
    # bid/ask that caused false 50%-spread vetoes); fall back to Yahoo
    try:
        from bot import alpaca
        bid = ask = None
        if alpaca.configured():
            bid, ask = alpaca.latest_quote(ticker)
        if not (bid and ask):
            info = tkr.info or {}
            bid, ask = info.get("bid"), info.get("ask")
        if bid and ask and ask > bid > 0:
            m["spread_pct"] = round((ask - bid) / ((ask + bid) / 2) * 100, 2)
    except Exception:
        pass

    try:
        expiries = tkr.options
        if expiries and m["last"]:
            chain = tkr.option_chain(expiries[0])
            calls, puts = chain.calls, chain.puts
            if not calls.empty:
                atm = calls.iloc[(calls["strike"] - m["last"]).abs().argsort()[:1]]
                iv = float(atm["impliedVolatility"].iloc[0])
                if iv > 0.01:
                    m["atm_iv"] = round(iv, 2)
            cv = float(calls["volume"].fillna(0).sum())
            pv = float(puts["volume"].fillna(0).sum())
            if cv + pv > 20:  # ignore meaninglessly thin option volume
                m["call_put_ratio"] = round(cv / max(pv, 1.0), 2)
    except Exception:
        pass

    return m


def confluence_check(cfg, ticker, news_sc, reddit_info=None, n_insiders=0):
    """(ok, detail). ok is True when enough independent checks confirm the
    entry and nothing triggers a hard veto."""
    c = cfg["confluence"]
    m = compute_metrics(ticker)
    checks = {
        "unusual_volume": None if m["rvol"] is None else m["rvol"] >= c["rvol_min"],
        "above_vwap": m["above_vwap"],
        "momentum": None if m["ret5d_pct"] is None or m["above_ma20"] is None
                    else (m["ret5d_pct"] > c["momentum_min_5d_pct"] and m["above_ma20"]),
        "tight_spread": None if m["spread_pct"] is None
                        else m["spread_pct"] <= c["max_spread_pct"],
        "price_action": None if m["day_range_pos"] is None or m["extension_pct"] is None
                        else (m["day_range_pos"] >= 0.5
                              and m["extension_pct"] <= c["max_extension_pct"]),
        "news_ok": news_sc >= 0,
        "options_flow": None if m["call_put_ratio"] is None
                        else m["call_put_ratio"] > 1.0,
    }
    from bot.signals.dilution import check_dilution
    dil = check_dilution(cfg, ticker)
    checks["clean_dilution_history"] = not dil["chronic"]
    vetoes = []
    if m["spread_pct"] is not None and m["spread_pct"] > c["hard_fail_spread_pct"]:
        vetoes.append("spread {}% > {}%".format(m["spread_pct"], c["hard_fail_spread_pct"]))
    if m["atm_iv"] is not None and m["atm_iv"] > c["max_iv"]:
        vetoes.append("ATM IV {:.0%} > {:.0%} (binary-event risk)".format(m["atm_iv"], c["max_iv"]))
    if pump_risk(reddit_info, m["last"], n_insiders):
        vetoes.append("reddit pump risk: mention spike on cheap stock without insider support")
    e_days = days_to_earnings(ticker)
    if e_days is not None and 0 <= e_days <= c["avoid_earnings_days"]:
        vetoes.append("earnings in {}d (binary-event risk)".format(e_days))
    if dil["veto"]:
        vetoes.append("dilution risk: offering/shelf filing {}d ago ({} in 90d)".format(
            dil["days_since_last"], dil["recent_filings"]))

    passed = sum(1 for v in checks.values() if v is True)
    applicable = sum(1 for v in checks.values() if v is not None)
    ok = not vetoes and passed >= c["min_checks_passed"]
    detail = {"checks": checks, "passed": passed, "applicable": applicable,
              "vetoes": vetoes, "metrics": m}
    return ok, detail


def summarize(detail):
    ck = detail["checks"]
    parts = ["{}/{} pass".format(detail["passed"], detail["applicable"])]
    parts += [k for k, v in ck.items() if v is True]
    fails = [k for k, v in ck.items() if v is False]
    if fails:
        parts.append("FAIL: " + ",".join(fails))
    if detail["vetoes"]:
        parts.append("VETO: " + "; ".join(detail["vetoes"]))
    return " | ".join(parts)
