"""Unsupervised market-regime detection — K-means on price action, no labels.

Clusters the last ~2 years of daily (realized vol, trend, breadth) into 3
states from bars.db and names them by their properties:

  calm_drift    low vol, mild trend      — momentum entries behave
  trending      elevated vol, real trend — catalysts follow through
  stress        high vol, weak/neg trend — chop and gap risk

Writes data/quant_regime.json with today's state + history. This is the
UNSUPERVISED cross-check on Claude's daily regime call (research.json) —
when the two disagree, the study session investigates why. Advisory only
until validated: the dynamic caps keep following the research regime.
"""
import datetime as dt
import json
import os

from bot.config import DATA_DIR
from bot import barcache

OUT = os.path.join(DATA_DIR, "quant_regime.json")


def run(years=2):
    import numpy as np
    import pandas as pd
    import sqlite3
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    cutoff = (dt.date.today() - dt.timedelta(days=int(years * 365.25))).isoformat()
    con = sqlite3.connect(barcache.DB)
    spy = pd.read_sql_query(
        "SELECT date, close FROM bars WHERE ticker='SPY' AND date>=? ORDER BY date",
        con, params=(cutoff,))
    # market breadth from a broad slice: share of tickers above their 20d mean
    uni = pd.read_sql_query(
        "SELECT ticker, date, close FROM bars WHERE date>=? AND ticker IN ("
        "SELECT DISTINCT ticker FROM bars ORDER BY RANDOM() LIMIT 300)",
        con, params=((dt.date.today() - dt.timedelta(days=140)).isoformat(),))
    con.close()
    if len(spy) < 200:
        # PWB stock dump excludes ETFs — fetch SPY once and cache it
        import yfinance as yf
        h = yf.download("SPY", period="2y", interval="1d", progress=False,
                        auto_adjust=True)
        if h is None or len(h) < 200:
            return {"error": "SPY history unavailable"}
        sub = h[["Close", "Volume"]].dropna()
        sub.columns = ["Close", "Volume"]
        barcache.store({"SPY": sub})
        spy = pd.DataFrame({"date": [ix.strftime("%Y-%m-%d") for ix in sub.index],
                            "close": sub["Close"].values})

    px = spy.set_index("date")["close"]
    ret = px.pct_change()
    feats = pd.DataFrame({
        "vol20": ret.rolling(20).std() * (252 ** 0.5),
        "trend20": px.pct_change(20),
        "dd": px / px.cummax() - 1,
    }).dropna()

    X = StandardScaler().fit_transform(feats.values)
    km = KMeans(n_clusters=3, n_init=10, random_state=7).fit(X)
    feats["state"] = km.labels_

    # name clusters by their character, not their arbitrary index
    prof = feats.groupby("state")[["vol20", "trend20"]].mean()
    names = {}
    stress = prof["vol20"].idxmax()
    calm = prof["vol20"].idxmin()
    names[stress] = "stress"
    names[calm] = "calm_drift"
    names[[i for i in prof.index if i not in (stress, calm)][0]] = "trending"

    today = feats.iloc[-1]
    state = names[int(today["state"])]
    hist = [names[int(s)] for s in feats["state"].iloc[-10:]]

    # breadth today
    breadth = None
    try:
        g = uni.sort_values(["ticker", "date"]).groupby("ticker")
        n_above = n_tot = 0
        for _, sub in g:
            if len(sub) >= 21:
                n_tot += 1
                if sub["close"].iloc[-1] > sub["close"].iloc[-20:].mean():
                    n_above += 1
        breadth = round(100 * n_above / n_tot, 1) if n_tot else None
    except Exception:
        pass

    # Gaussian HMM (hmmlearn): temporal regime model — unlike K-means it
    # knows states PERSIST (transition matrix), the field-standard approach
    hmm_state, hmm_stick = None, None
    try:
        from hmmlearn.hmm import GaussianHMM
        Xh = np.column_stack([ret.loc[feats.index].fillna(0).values,
                              feats["vol20"].values])
        hm = GaussianHMM(n_components=3, covariance_type="diag",
                         n_iter=200, random_state=7).fit(Xh)
        hs = hm.predict(Xh)
        hvol = {s: Xh[hs == s, 1].mean() for s in set(hs)}
        hnames = {max(hvol, key=hvol.get): "stress",
                  min(hvol, key=hvol.get): "calm_drift"}
        for s in set(hs):
            hnames.setdefault(s, "trending")
        hmm_state = hnames[int(hs[-1])]
        hmm_stick = round(float(hm.transmat_[hs[-1], hs[-1]]), 3)
    except Exception:
        pass

    # CUSUM structural-break filter (Lopez de Prado): flags when cumulative
    # deviations from the running mean exceed h = 5 sigma — a regime break.
    # Use: a tune/walkforward window that CROSSES the latest break mixes two
    # different markets (the 7/14 exit-window conflict, made measurable).
    breaks = []
    try:
        r = ret.dropna().values
        mu = float(r[:60].mean()) if len(r) > 60 else float(r.mean())
        sigma = float(r[:60].std()) if len(r) > 60 else float(r.std())
        h = 5.0 * sigma
        s_pos = s_neg = 0.0
        dates_r = list(ret.dropna().index)
        for i, x in enumerate(r):
            s_pos = max(0.0, s_pos + x - mu)
            s_neg = min(0.0, s_neg + x - mu)
            if s_pos > h or s_neg < -h:
                breaks.append(dates_r[i])
                s_pos = s_neg = 0.0
                mu = float(r[max(0, i - 60):i + 1].mean())
    except Exception:
        pass
    last_break = breaks[-1] if breaks else None
    days_since = None
    if last_break:
        days_since = (dt.date.today() - dt.date.fromisoformat(last_break)).days

    # CROSS-BOT FEED (2026-07-15): goldbot on this same box maintains real
    # 10Y yields, DXY and a gold HMM regime — macro context equities lack.
    # Rising real yields + strong dollar = headwind for risk assets broadly.
    gold_macro = None
    try:
        gm = json.load(open(os.path.expanduser("~/goldbot/data/macro.json")))
        gr = json.load(open(os.path.expanduser("~/goldbot/data/regime.json")))
        ry = gm.get("real_yield", {}).get("series", [])
        dxy = gm.get("dxy", {}).get("series", [])
        gold_macro = {
            "real_yield_10y": ry[-1][1] if ry else None,
            "real_yield_5d_chg": round(ry[-1][1] - ry[-6][1], 3) if len(ry) > 5 else None,
            "dxy": round(dxy[-1][1], 2) if dxy else None,
            "gold_regime": gr.get("regime"),
        }
    except Exception:
        pass

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gold_macro": gold_macro,
        "method": "KMeans k=3 on SPY (vol20, trend20, drawdown), 2y daily",
        "hmm_state": hmm_state,
        "hmm_persistence": hmm_stick,
        "state": state,
        "hmm_agrees_with_kmeans": (hmm_state == state) if hmm_state else None,
        "last_10_days": hist,
        "spy_vol20_ann": round(float(today["vol20"]) * 100, 1),
        "spy_trend20_pct": round(float(today["trend20"]) * 100, 2),
        "breadth_pct_above_20dma": breadth,
        "cusum_breaks_2y": breaks[-6:],
        "last_structural_break": last_break,
        "days_since_break": days_since,
        "tune_window_clean": (days_since is None or days_since > 185),
        "cluster_profiles": {names[i]: {"vol": round(float(r["vol20"]) * 100, 1),
                                        "trend": round(float(r["trend20"]) * 100, 2)}
                             for i, r in prof.iterrows()},
        "note": ("Unsupervised cross-check on the research regime. Advisory "
                 "until the study session validates state vs outcomes; the "
                 "dynamic caps follow research.json, not this."),
    }
    json.dump(out, open(OUT, "w"), indent=1)
    return out


if __name__ == "__main__":
    r = run()
    print("quant regime:", r.get("state"), "| vol", r.get("spy_vol20_ann"),
          "| trend", r.get("spy_trend20_pct"), "| breadth", r.get("breadth_pct_above_20dma"))
    print("last 10d:", " ".join(r.get("last_10_days", [])))
