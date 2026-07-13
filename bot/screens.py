"""Night-shift universe screens — idle-time work for the box.

Runs nightly (systemd night-screens.timer, after cache-warm) over the FULL
bars.db universe (7,700+ tickers from the PWB import) and writes
data/screens.json with the strategy-gap screens the study backlog identified:

  rvol            last-day volume / 20-day average volume
  hi52_proximity  last close / 52-week max close (1.0 = at the high)
  mom13w_rank     13-week return, cross-sectional percentile vs the universe

Consumers: the dashboard/radar, the intel + risk + study Claude sessions, and
(after study validation, not before) the scorer. Price band and a liquidity
floor keep the output in our tradeable pond.
"""
import datetime as dt
import json
import os

from bot.config import DATA_DIR
from bot import barcache

OUT = os.path.join(DATA_DIR, "screens.json")
PRICE_LO, PRICE_HI = 1.0, 20.0
MIN_AVG_VOL = 100_000          # shares/day — skip untradeable dust


def build(top_n=40):
    import pandas as pd
    import sqlite3
    cutoff = (dt.date.today() - dt.timedelta(days=380)).isoformat()
    con = sqlite3.connect(barcache.DB)
    df = pd.read_sql_query(
        "SELECT ticker, date, close, volume FROM bars WHERE date >= ?",
        con, params=(cutoff,))
    con.close()
    if df.empty:
        return {}

    df = df.sort_values(["ticker", "date"])
    g = df.groupby("ticker")
    last = g.tail(1).set_index("ticker")
    stats = pd.DataFrame({
        "close": last["close"],
        "last_date": last["date"],
        "avg_vol20": g["volume"].apply(lambda s: s.tail(20).mean()),
        "last_vol": last["volume"],
        "hi52": g["close"].max(),
        "close_13w_ago": g["close"].apply(
            lambda s: s.iloc[-66] if len(s) >= 66 else None),
    })
    # tradeable pond only, and rows must be recent (dead tickers linger in PWB)
    fresh_floor = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    stats = stats[(stats["close"] >= PRICE_LO) & (stats["close"] <= PRICE_HI)
                  & (stats["avg_vol20"] >= MIN_AVG_VOL)
                  & (stats["last_date"] >= fresh_floor)].copy()

    stats["rvol"] = stats["last_vol"] / stats["avg_vol20"]
    stats["hi52_proximity"] = stats["close"] / stats["hi52"]
    ret13 = (stats["close"] / stats["close_13w_ago"] - 1).dropna()
    stats["mom13w_rank"] = ret13.rank(pct=True).round(3) * 100

    def _top(col, ascending=False):
        rows = stats.dropna(subset=[col]).sort_values(col, ascending=ascending)
        return [{"ticker": t, col: round(float(r[col]), 3),
                 "close": round(float(r["close"]), 2)}
                for t, r in rows.head(top_n).iterrows()]

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "universe_screened": int(len(stats)),
        "screens": {
            "rvol_top": _top("rvol"),
            "near_52wk_high": _top("hi52_proximity"),
            "momentum_13w_top": _top("mom13w_rank"),
        },
        "lookup": {t: {"rvol": round(float(r["rvol"]), 2) if pd.notna(r["rvol"]) else None,
                       "hi52_proximity": round(float(r["hi52_proximity"]), 3),
                       "mom13w_rank": round(float(r["mom13w_rank"]), 1)
                       if pd.notna(r["mom13w_rank"]) else None}
                   for t, r in stats.iterrows()},
        "note": ("Screens are RESEARCH data for the Claude sessions and radar — "
                 "not yet score inputs; the study session validates each screen "
                 "against outcomes before the scorer may consume it."),
    }
    json.dump(out, open(OUT, "w"))
    return out


if __name__ == "__main__":
    r = build()
    print("screens:", r.get("universe_screened", 0), "tickers in pond ->", OUT)
    for name, rows in (r.get("screens") or {}).items():
        print(" ", name, [x["ticker"] for x in rows[:8]])
