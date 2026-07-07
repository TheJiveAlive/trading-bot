"""Dump the last week of ledger activity to data/review_input.json so the
weekly review session starts from structured facts instead of raw SQL."""
import datetime as dt
import json
import os

from bot import config, ledger, market
from bot.config import DATA_DIR


def main():
    config.load()
    con = ledger.connect()
    week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()

    cols = ("ts", "ticker", "side", "shares", "price", "value", "mode", "reason")
    trades = [dict(zip(cols, r)) for r in con.execute(
        "SELECT ts,ticker,side,shares,price,value,mode,reason FROM trades "
        "WHERE ts>=? ORDER BY ts", (week_ago,))]
    decisions = [dict(zip(("ts", "kind", "detail"), r)) for r in con.execute(
        "SELECT ts,kind,detail FROM decisions WHERE ts>=? ORDER BY ts", (week_ago,))]
    candidates = [dict(zip(("ts", "ticker", "score"), r)) for r in con.execute(
        "SELECT ts,ticker,MAX(score) FROM scan_candidates WHERE ts>=? "
        "GROUP BY ticker ORDER BY MAX(score) DESC LIMIT 15", (week_ago,))]

    positions = []
    for p in ledger.open_positions(con):
        price = market.last_price(p["ticker"])
        positions.append({**p, "current_price": price,
                          "unrealized_pct": round((price / p["avg_cost"] - 1) * 100, 1)
                          if price and p["avg_cost"] else None})

    out = {
        "generated": ledger.now(),
        "cash": ledger.cash(con),
        "positions": positions,
        "trades_this_week": trades,
        "decisions_this_week": decisions,
        "top_candidates_this_week": candidates,
    }
    con.close()
    path = os.path.join(DATA_DIR, "review_input.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", path)


if __name__ == "__main__":
    main()
