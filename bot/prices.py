"""Writes data/prices.json — a tiny live-quote file the dashboard polls from
the browser (via raw.githubusercontent CORS). Uses Alpaca when keyed, else
Yahoo. Kept lightweight so it can run every few minutes cheaply.
"""
import datetime as dt
import json
import os

from bot import config, ledger, market
from bot.config import DATA_DIR


def build():
    config.load()
    con = ledger.connect()
    held = [p["ticker"] for p in ledger.open_positions(con)]
    # include the most recent scan candidates so the watchlist ticks live too
    cand = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM scan_candidates ORDER BY id DESC LIMIT 10").fetchall()]
    con.close()
    tickers = list(dict.fromkeys(held + cand))[:20]

    prices = {}
    try:
        from bot.alpaca import latest_prices, configured
        if configured():
            prices = latest_prices(tickers)
    except Exception:
        prices = {}
    # fill any gaps with Yahoo
    for t in tickers:
        if t not in prices:
            p = market.last_price(t)
            if p:
                prices[t] = round(p, 4)

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "alpaca" if _alpaca_on() else "yahoo",
        "prices": {t: round(v, 4) for t, v in prices.items()},
        "held": held,
    }
    path = os.path.join(DATA_DIR, "prices.json")
    with open(path, "w") as f:
        json.dump(out, f)

    # live decision feed for the dashboard (same commit cadence as prices)
    con = ledger.connect()
    decisions = [{"ts": r[0], "kind": r[1], "detail": r[2][:200]} for r in
                 con.execute("SELECT ts,kind,detail FROM decisions "
                             "ORDER BY id DESC LIMIT 14")]
    trades = [{"ts": r[0], "side": r[1], "ticker": r[2], "shares": r[3],
               "price": r[4]} for r in
              con.execute("SELECT ts,side,ticker,shares,price FROM trades "
                          "ORDER BY id DESC LIMIT 6")]
    con.close()
    with open(os.path.join(DATA_DIR, "feed.json"), "w") as f:
        json.dump({"generated": out["generated"], "decisions": decisions,
                   "trades": trades}, f)
    return path, out


def _alpaca_on():
    try:
        from bot.alpaca import configured
        return configured()
    except Exception:
        return False


if __name__ == "__main__":
    path, out = build()
    print("wrote", path, "-", len(out["prices"]), "quotes via", out["source"])
