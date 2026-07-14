"""Lorentzian k-NN classification — nightly ML sweep over the whole pond.

Port of the approach behind TradingView's "Machine Learning: Lorentzian
Classification": for each ticker, find the k historical days most similar to
TODAY in feature space using the LORENTZIAN distance sum(log(1+|x-y|)) —
which fattens tails and handles outliers/warped price-time better than
Euclidean — and vote on what happened over the following 4 sessions.

Differences from the TV original, forced by our data (bars.db is close +
volume only, no high/low): features are close/volume-derived — RSI14, ROC10,
20d z-score, 10d realized vol, distance from 50d MA, relative volume.

Output: data/lorentzian.json — per-ticker score in [-1, +1] (mean direction
of the k neighbours' 4-day-forward returns) + hit-consistency. RESEARCH-ONLY
until the study session validates score-vs-outcome (prompt item 5e); the
scorer does not consume it. Runs nightly on the full ~2,000-ticker pond —
this is the box's CPU actually earning its keep.
"""
import datetime as dt
import json
import os

from bot.config import DATA_DIR
from bot import barcache

OUT = os.path.join(DATA_DIR, "lorentzian.json")
K = 8
HORIZON = 4          # predict 4-session-forward direction, like the TV script
MIN_BARS = 260
PRICE_LO, PRICE_HI = 1.0, 20.0
MIN_AVG_VOL = 100_000


def _features(close, vol):
    import numpy as np
    import pandas as pd
    delta = close.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    ret = close.pct_change()
    f = pd.DataFrame({
        "rsi": rsi,
        "roc10": close.pct_change(10) * 100,
        "z20": (close - close.rolling(20).mean()) / close.rolling(20).std(),
        "vol10": ret.rolling(10).std() * 100,
        "ma50d": (close / close.rolling(50).mean() - 1) * 100,
        "rvol": vol / vol.rolling(20).mean(),
    })
    return f


def _score_ticker(close, vol):
    """(score, consistency, n_neighbors) or None."""
    import numpy as np
    f = _features(close, vol).dropna()
    if len(f) < MIN_BARS:
        return None
    X = f.values
    # standardize per ticker so features share scale
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    X = (X - mu) / sd
    query = X[-1]
    # candidate neighbours: all rows old enough to have a known 4d future
    hist = X[:-HORIZON - 1]
    if len(hist) < 60:
        return None
    dist = np.log1p(np.abs(hist - query)).sum(axis=1)     # Lorentzian
    idx = np.argpartition(dist, K)[:K]
    closes = close.loc[f.index].values
    futs = []
    for i in idx:
        fut = closes[i + HORIZON] / closes[i] - 1
        futs.append(np.sign(fut))
    score = float(np.mean(futs))
    consistency = float(np.abs(score))
    return round(score, 3), round(consistency, 3), K


def run(top_n=30):
    import pandas as pd
    import sqlite3
    cutoff = (dt.date.today() - dt.timedelta(days=550)).isoformat()
    fresh_floor = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    con = sqlite3.connect(barcache.DB)
    df = pd.read_sql_query(
        "SELECT ticker, date, close, volume FROM bars WHERE date >= ?",
        con, params=(cutoff,))
    con.close()
    df = df.sort_values(["ticker", "date"])
    out_t, scanned = {}, 0
    for tkr, sub in df.groupby("ticker"):
        c = sub["close"]
        if not (PRICE_LO <= c.iloc[-1] <= PRICE_HI):
            continue
        if sub["volume"].tail(20).mean() < MIN_AVG_VOL:
            continue
        if sub["date"].iloc[-1] < fresh_floor:
            continue
        r = _score_ticker(c.reset_index(drop=True),
                          sub["volume"].reset_index(drop=True))
        scanned += 1
        if r:
            out_t[tkr] = {"score": r[0], "consistency": r[1],
                          "close": round(float(c.iloc[-1]), 2)}
    ranked = sorted(out_t.items(), key=lambda kv: kv[1]["score"])
    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method": "k-NN (k={}) Lorentzian distance, {}-day horizon, "
                  "close/volume features".format(K, HORIZON),
        "pond_scanned": scanned,
        "bullish_top": [{"ticker": t, **v} for t, v in ranked[-top_n:][::-1]],
        "bearish_top": [{"ticker": t, **v} for t, v in ranked[:top_n]],
        "lookup": out_t,
        "note": ("RESEARCH-ONLY until the study session validates score vs "
                 "outcomes. A +1.0 means all k Lorentzian neighbours of "
                 "today's setup resolved UP over the next 4 sessions."),
    }
    json.dump(out, open(OUT, "w"))
    return out


if __name__ == "__main__":
    r = run()
    print("lorentzian:", r.get("pond_scanned", 0), "tickers scanned ->", OUT)
    print("  bullish:", [(x["ticker"], x["score"]) for x in r.get("bullish_top", [])[:6]])
    print("  bearish:", [(x["ticker"], x["score"]) for x in r.get("bearish_top", [])[:6]])
