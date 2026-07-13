"""Local daily-bar cache (SQLite on disk).

Backtests download each ticker's history ONCE; every run after reads it from
disk in milliseconds instead of re-hitting Alpaca/Yahoo. Free, server-resident,
and Yahoo-sourced so it reaches the small-caps Alpaca's free tier misses.

Table: bars(ticker, date, close, volume) — one row per trading day, upserted.
"""
import datetime as dt
import os
import sqlite3

from bot.config import CACHE_DIR

DB = os.path.join(CACHE_DIR, "bars.db")


def _con():
    os.makedirs(CACHE_DIR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS bars ("
              "ticker TEXT, date TEXT, close REAL, volume REAL, "
              "PRIMARY KEY(ticker, date))")
    return c


def load(tickers, t0, t1):
    """{ticker: DataFrame(Close, Volume)} for tickers with adequate, fresh
    cached coverage of [t0, t1] (ISO date strings). Others are omitted so the
    caller downloads only what's missing."""
    import pandas as pd
    out = {}
    fresh_floor = (dt.date.fromisoformat(t1[:10]) - dt.timedelta(days=7)).isoformat()
    try:
        c = _con()
        for t in tickers:
            rows = c.execute(
                "SELECT date, close, volume FROM bars "
                "WHERE ticker=? AND date>=? AND date<=? ORDER BY date",
                (t, t0[:10], t1[:10])).fetchall()
            if len(rows) >= 25 and rows[-1][0] >= fresh_floor:
                idx = pd.to_datetime([r[0] for r in rows])
                out[t] = pd.DataFrame(
                    {"Close": [r[1] for r in rows],
                     "Volume": [r[2] for r in rows]}, index=idx)
        c.close()
    except Exception:
        pass
    return out


def store(hist):
    """Persist {ticker: DataFrame(Close, Volume)} to the cache (upsert)."""
    import pandas as pd
    try:
        c = _con()
        for t, df in (hist or {}).items():
            rows = []
            for ix, r in df.iterrows():
                close = r.get("Close")
                if close is None or pd.isna(close):
                    continue
                vol = r.get("Volume")
                rows.append((t, ix.strftime("%Y-%m-%d"), float(close),
                             float(vol) if pd.notna(vol) else 0.0))
            if rows:
                c.executemany("INSERT OR REPLACE INTO bars "
                              "(ticker, date, close, volume) VALUES (?,?,?,?)", rows)
        c.commit()
        c.close()
    except Exception:
        pass


def stats():
    try:
        c = _con()
        nt = c.execute("SELECT COUNT(DISTINCT ticker) FROM bars").fetchone()[0]
        nr = c.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
        span = c.execute("SELECT MIN(date), MAX(date) FROM bars").fetchone()
        c.close()
        return {"tickers": nt, "rows": nr, "from": span[0], "to": span[1]}
    except Exception:
        return {"tickers": 0, "rows": 0}


def warm(tickers, years=3):
    """Bulk-download and cache daily bars for a ticker list (overnight job).
    Skips tickers already fresh in the cache."""
    import time
    import yfinance as yf
    end = dt.date.today()
    start = end - dt.timedelta(days=int(years * 365.25))
    t0, t1 = start.isoformat(), (end + dt.timedelta(days=1)).isoformat()
    have = set(load(tickers, t0, t1))
    todo = [t for t in tickers if t not in have]
    print("cache warm: {} cached, {} to fetch".format(len(have), len(todo)), flush=True)
    added = 0
    for i in range(0, len(todo), 150):
        chunk = todo[i:i + 150]
        try:
            df = yf.download(chunk, start=t0, end=t1, interval="1d",
                             progress=False, group_by="ticker", threads=True,
                             auto_adjust=True)
            batch = {}
            for t in chunk:
                try:
                    sub = (df[t] if len(chunk) > 1 else df)[["Close", "Volume"]].dropna()
                    if len(sub) >= 25:
                        batch[t] = sub
                except Exception:
                    continue
            store(batch)
            added += len(batch)
            print("  warmed {}/{} ({} total)".format(i + len(chunk), len(todo), added), flush=True)
        except Exception as e:
            print("  chunk error: {}".format(e), flush=True)
        time.sleep(1.5)
    print("cache warm done:", stats(), flush=True)
    return added
