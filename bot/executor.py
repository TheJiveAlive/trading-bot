"""Order execution.

paper mode: fills immediately at last market price into the local ledger.
live mode:  records the trade in the ledger AND appends the order to
            data/pending_orders.json, which a Claude session executes via the
            robinhood-trading connector (requires the connector to be
            authorized). Until each order is confirmed there, treat ledger
            state in live mode as intended, not executed.
"""
import json
import os

from bot.config import DATA_DIR
from bot import ledger, notify

PENDING_ORDERS = os.path.join(DATA_DIR, "pending_orders.json")


def _position(con, ticker):
    row = con.execute("SELECT shares, avg_cost FROM positions "
                      "WHERE ticker=? AND status='open'", (ticker,)).fetchone()
    return {"shares": row[0], "avg_cost": row[1]} if row else None


def _portfolio_positions(con):
    """Open positions enriched with current price and unrealized P/L."""
    from bot import market
    out = []
    for p in ledger.open_positions(con):
        price = market.last_price(p["ticker"])
        out.append({**p, "current_price": price,
                    "unrealized_pct": round((price / p["avg_cost"] - 1) * 100, 1)
                    if price and p["avg_cost"] else None})
    return out


def _queue_order(order):
    orders = []
    if os.path.exists(PENDING_ORDERS):
        with open(PENDING_ORDERS) as f:
            orders = json.load(f)
    orders.append(order)
    with open(PENDING_ORDERS, "w") as f:
        json.dump(orders, f, indent=2)


def execute(con, cfg, side, ticker, shares, price, reason):
    mode = cfg["mode"]
    pnl_line = ""
    if side == "buy":
        ledger.record_buy(con, ticker, shares, price, mode, reason)
    else:
        pos = _position(con, ticker)
        ledger.record_sell(con, ticker, shares, price, mode, reason)
        if pos and pos["avg_cost"]:
            pnl = (price - pos["avg_cost"]) * shares
            pnl_pct = (price / pos["avg_cost"] - 1) * 100
            pnl_line = "P/L: {}${:.2f} ({:+.1f}%)\n".format(
                "+" if pnl >= 0 else "-", abs(pnl), pnl_pct)
    if mode == "live":
        _queue_order({
            "ts": ledger.now(), "side": side, "ticker": ticker,
            "shares": shares, "limit_price_hint": round(price, 2),
            "reason": reason, "status": "pending",
        })

    from bot import emailfmt
    positions = _portfolio_positions(con)
    reasons = [r.strip() for r in reason.split(";") if r.strip()]
    pnl_usd = pnl_pct = None
    if pnl_line:
        pnl_usd = (price - pos["avg_cost"]) * shares
        pnl_pct = (price / pos["avg_cost"] - 1) * 100
    note = None
    if mode == "live":
        note = ("Live mode: this order is QUEUED in pending_orders.json and is "
                "not executed until the Robinhood connector processes it.")
    subject, html, text = emailfmt.trade_email(
        side, ticker, shares, price, mode, reasons, positions,
        ledger.cash(con), pnl_usd=pnl_usd, pnl_pct=pnl_pct, note=note)
    chart = emailfmt.price_chart_png(
        ticker,
        entry_price=(price if side == "buy" else (pos["avg_cost"] if pos else None)),
        exit_price=(price if side == "sell" else None))
    notify.send_html_email(subject, html, text, images={"chart": chart})
    return {"mode": mode, "side": side, "ticker": ticker,
            "shares": shares, "price": price}
