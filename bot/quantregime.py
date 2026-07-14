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

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method": "KMeans k=3 on SPY (vol20, trend20, drawdown), 2y daily",
        "state": state,
        "last_10_days": hist,
        "spy_vol20_ann": round(float(today["vol20"]) * 100, 1),
        "spy_trend20_pct": round(float(today["trend20"]) * 100, 2),
        "breadth_pct_above_20dma": breadth,
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
