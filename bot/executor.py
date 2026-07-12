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


def _route_live_order(cfg, side, ticker, shares, price, reason):
    """Send a live order to the configured broker. Returns a human note for
    the email/log. Falls back to the pending_orders.json queue on any error so
    nothing is silently lost."""
    broker = cfg.get("broker", {}).get("name", "trading212")
    signed = shares if side == "buy" else -shares
    if broker == "trading212":
        from bot import broker_t212
        # No key yet → clean dry-run note, never a queued error order. This makes
        # flipping mode:live safe before the T212_API_KEY secret is set.
        if not broker_t212.configured():
            return ("DRY-RUN (Trading 212 not connected — no API key): would {} {} x{}. "
                    "Set T212_API_KEY to route this order.".format(side, ticker, shares))
        try:
            res = broker_t212.place_market_order(
                cfg, ticker, signed, price_hint=price,
                dry_run=not cfg.get("broker", {}).get("live_orders_enabled", False))
            if res.get("dry_run"):
                return ("DRY-RUN (live_orders_enabled=false): would {} {} x{} on "
                        "Trading 212 {}.".format(side, ticker, shares, res["environment"]))
            return "SENT to Trading 212: {} {} x{} (order id {}).".format(
                side, ticker, shares, res.get("response", {}).get("id", "?"))
        except Exception as e:
            _queue_order({"ts": ledger.now(), "side": side, "ticker": ticker,
                          "shares": shares, "limit_price_hint": round(price, 2),
                          "reason": reason, "status": "pending",
                          "error": str(e)})
            return "Broker error ({}) — queued to pending_orders.json instead.".format(e)
    _queue_order({"ts": ledger.now(), "side": side, "ticker": ticker,
                  "shares": shares, "limit_price_hint": round(price, 2),
                  "reason": reason, "status": "pending"})
    return "Queued to pending_orders.json (broker '{}').".format(broker)


def _realistic_fill(cfg, side, ticker, price):
    """Make paper fills honest: buy at the ASK, sell at the BID (real Alpaca
    quote when available, else an estimated spread). Penny/small-cap spreads are
    1-10%, so last-price fills overstate P/L by that much per round-trip — this
    makes the paper account predict live reality instead of flattering it."""
    if not cfg.get("realistic_fills", True):
        return price
    bid = ask = None
    try:
        from bot import alpaca
        if alpaca.configured():
            bid, ask = alpaca.latest_quote(ticker)
    except Exception:
        pass
    if bid and ask and ask > bid > 0:
        return ask if side == "buy" else bid
    # no quote → estimate spread by price tier (thinner/cheaper = wider)
    est = 0.04 if price < 1 else (0.02 if price < 5 else 0.008)
    return price * (1 + est / 2) if side == "buy" else price * (1 - est / 2)


def execute(con, cfg, side, ticker, shares, price, reason, parts=None, catalyst=None):
    mode = cfg["mode"]
    if mode == "paper":
        adj = _realistic_fill(cfg, side, ticker, price)
        if abs(adj - price) > 1e-6:
            reason += " | fill ${:.4f} (spread-adjusted from ${:.4f})".format(adj, price)
        price = round(adj, 4)
    pnl_line = ""
    if side == "buy":
        ledger.record_buy(con, ticker, shares, price, mode, reason)
        if parts or catalyst:
            con.execute("INSERT INTO trade_signals (ts,ticker,parts,catalyst) "
                        "VALUES (?,?,?,?)",
                        (ledger.now(), ticker, json.dumps(parts or {}), catalyst))
    else:
        pos = _position(con, ticker)
        ledger.record_sell(con, ticker, shares, price, mode, reason)
        if pos and pos["avg_cost"]:
            pnl = (price - pos["avg_cost"]) * shares
            pnl_pct = (price / pos["avg_cost"] - 1) * 100
            pnl_line = "P/L: {}${:.2f} ({:+.1f}%)\n".format(
                "+" if pnl >= 0 else "-", abs(pnl), pnl_pct)
            # reward attribution: credit/blame the signals + catalyst that drove entry
            row = con.execute("SELECT parts, catalyst FROM trade_signals WHERE ticker=? "
                              "ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
            if row:
                for signal, contribution in json.loads(row[0] or "{}").items():
                    con.execute("INSERT INTO signal_rewards "
                                "(ts,ticker,signal,contribution,pnl_pct) "
                                "VALUES (?,?,?,?,?)",
                                (ledger.now(), ticker, signal,
                                 float(contribution), round(pnl_pct, 2)))
                if row[1]:  # news catalyst training marker → outcome
                    con.execute("INSERT INTO catalyst_rewards "
                                "(ts,ticker,catalyst,pnl_pct) VALUES (?,?,?,?)",
                                (ledger.now(), ticker, row[1], round(pnl_pct, 2)))
    broker_note = ""
    if mode == "live":
        broker_note = _route_live_order(cfg, side, ticker, shares, price, reason)

    from bot import emailfmt
    positions = _portfolio_positions(con)
    reasons = [r.strip() for r in reason.split(";") if r.strip()]
    pnl_usd = pnl_pct = None
    if pnl_line:
        pnl_usd = (price - pos["avg_cost"]) * shares
        pnl_pct = (price / pos["avg_cost"] - 1) * 100
    note = broker_note or None
    chart = emailfmt.price_chart_png(
        ticker,
        entry_price=(price if side == "buy" else (pos["avg_cost"] if pos else None)),
        exit_price=(price if side == "sell" else None))
    subject, html, text = emailfmt.trade_email(
        side, ticker, shares, price, mode, reasons, positions,
        ledger.cash(con), pnl_usd=pnl_usd, pnl_pct=pnl_pct, note=note,
        has_chart=bool(chart))
    notify.send_html_email(subject, html, text,
                           images={"chart": chart} if chart else None)
    return {"mode": mode, "side": side, "ticker": ticker,
            "shares": shares, "price": price}
