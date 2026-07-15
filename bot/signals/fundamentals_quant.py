"""Quantitative fundamentals: Piotroski F-Score + Altman Z-Score (yfinance).

Compresses the balance sheet into two discrete, comparable numbers:

  piotroski  0-9   financial health (profitability, leverage, efficiency);
                    >=7 strong, <=3 weak — modest SCORE input (study validates)
  altman_z   float  bankruptcy probability; classic Z < 1.8 = distress zone —
                    used as a protective BUY VETO (a "cheap" stock that is
                    actually insolvent is the classic microcap trap)

Microcap statements are often missing/partial on yfinance: every metric is
fail-open (None) and the veto only fires on POSITIVE evidence of distress.
Statement fetches are slow, so results cache per-ticker for 3 days
(fundamentals move quarterly).
"""
import datetime as dt
import json
import os

from bot.config import CACHE_DIR

CACHE = os.path.join(CACHE_DIR, "fquant.json")
TTL_DAYS = 3


def _row(df, names):
    """First matching row value for the two most recent columns -> (cur, prev)."""
    try:
        for n in names:
            if n in df.index:
                s = df.loc[n].dropna()
                if len(s) >= 1:
                    cur = float(s.iloc[0])
                    prev = float(s.iloc[1]) if len(s) >= 2 else None
                    return cur, prev
    except Exception:
        pass
    return None, None


def _compute(ticker):
    import yfinance as yf
    t = yf.Ticker(ticker)
    try:
        inc = t.income_stmt
        bal = t.balance_sheet
        cf = t.cashflow
        info = t.info or {}
    except Exception:
        return {"piotroski": None, "altman_z": None}
    if inc is None or bal is None or inc.empty or bal.empty:
        return {"piotroski": None, "altman_z": None}

    ni, ni_p = _row(inc, ["Net Income", "Net Income Common Stockholders"])
    ta, ta_p = _row(bal, ["Total Assets"])
    cfo, _ = _row(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
    ltd, ltd_p = _row(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
    ca, ca_p = _row(bal, ["Current Assets"])
    cl, cl_p = _row(bal, ["Current Liabilities"])
    gp, gp_p = _row(inc, ["Gross Profit"])
    rev, rev_p = _row(inc, ["Total Revenue"])
    sh, sh_p = _row(bal, ["Ordinary Shares Number", "Share Issued"])
    re_, _ = _row(bal, ["Retained Earnings"])
    ebit, _ = _row(inc, ["EBIT", "Operating Income"])
    tl, _ = _row(bal, ["Total Liabilities Net Minority Interest", "Total Liabilities"])

    # ---- Piotroski F (each test only counts when its inputs exist) ----
    f, tests = 0, 0
    def add(cond):
        nonlocal f, tests
        if cond is not None:
            tests += 1
            if cond:
                f += 1
    roa = ni / ta if ni is not None and ta else None
    roa_p = (ni_p / ta_p) if ni_p is not None and ta_p else None
    add(roa is not None and roa > 0)                                  # 1 ROA>0
    add(cfo is not None and cfo > 0)                                  # 2 CFO>0
    add((roa is not None and roa_p is not None and roa > roa_p) if roa_p is not None else None)  # 3 dROA
    add((cfo > ni) if cfo is not None and ni is not None else None)   # 4 accruals
    add((ltd is not None and ltd_p is not None and ta and ta_p and
         ltd / ta <= ltd_p / ta_p) if ltd_p is not None else None)    # 5 leverage down
    add((ca / cl > ca_p / cl_p) if all(x for x in (ca, cl, ca_p, cl_p)) else None)  # 6 liquidity up
    add((sh <= sh_p * 1.02) if sh and sh_p else None)                 # 7 no dilution
    add((gp / rev > gp_p / rev_p) if all(x for x in (gp, rev, gp_p, rev_p)) else None)  # 8 margin up
    add((rev / ta > rev_p / ta_p) if all(x for x in (rev, ta, rev_p, ta_p)) else None)  # 9 turnover up
    piotroski = f if tests >= 5 else None   # need a real base of evidence

    # ---- Altman Z (classic; MVE from market cap) ----
    z = None
    try:
        mve = info.get("marketCap")
        if all(x is not None for x in (ca, cl, ta, re_, ebit, rev, tl)) and ta and tl and mve:
            wc = ca - cl
            z = round(1.2 * wc / ta + 1.4 * re_ / ta + 3.3 * ebit / ta
                      + 0.6 * mve / tl + 1.0 * rev / ta, 2)
    except Exception:
        pass
    return {"piotroski": piotroski, "piotroski_tests": tests, "altman_z": z}


def scores(ticker):
    """Cached {piotroski, altman_z} for a ticker (3-day TTL, fail-open)."""
    today = dt.date.today().isoformat()
    cache = {}
    try:
        cache = json.load(open(CACHE))
    except Exception:
        pass
    hit = cache.get(ticker)
    if hit and (dt.date.today() - dt.date.fromisoformat(hit["d"])).days < TTL_DAYS:
        return hit["v"]
    v = _compute(ticker)
    cache[ticker] = {"d": today, "v": v}
    try:
        json.dump(cache, open(CACHE, "w"))
    except Exception:
        pass
    return v


def piotroski_part(ticker, weight=1.0):
    """Modest bounded score part: F>=7 -> +0.75, >=5 -> +0.25, <=3 -> -0.5."""
    v = scores(ticker)
    fsc = v.get("piotroski")
    if fsc is None:
        return 0.0
    if fsc >= 7:
        return round(0.75 * weight, 2)
    if fsc >= 5:
        return round(0.25 * weight, 2)
    if fsc <= 3:
        return round(-0.5 * weight, 2)
    return 0.0


def z_distress(ticker):
    """(True, z) only on POSITIVE evidence of distress (classic Z < 1.8)."""
    v = scores(ticker)
    z = v.get("altman_z")
    return (z is not None and z < 1.8), z


if __name__ == "__main__":
    import sys
    for tk in (sys.argv[1:] or ["NTSK", "UUUU", "WRAP", "YEXT", "CAI"]):
        v = _compute(tk)
        print("{:6s} piotroski={} ({} tests)  altman_z={}".format(
            tk, v.get("piotroski"), v.get("piotroski_tests"), v.get("altman_z")))
