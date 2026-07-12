"""PANIC BUTTON: flatten the whole book — sell every open position at market,
cancel every pending broker order, email a summary.

  python run.py flatten          (or the 'panic-flatten' workflow on GitHub)

USER-TRIGGERED ONLY. Nothing in the bot calls this automatically — automatic
protection is the job of the circuit breakers (drawdown/daily-loss halts) which
stop BUYING; this is the human "get me out of everything now" lever the
going-live plan requires. Sells route through the normal executor, so in live
mode they hit Trading 212 and each one sends the usual trade email.
"""
from bot import config, ledger, market, notify


def _cancel_pending_broker_orders(cfg, report):
    """Cancel any resting orders at the broker so nothing fills after we flatten."""
    from bot import broker_t212
    if not (cfg.get("mode") == "live" and broker_t212.configured()):
        return 0
    cancelled = 0
    try:
        for o in broker_t212.list_orders(cfg) or []:
            oid = o.get("id")
            try:
                broker_t212.cancel_order(cfg, oid)
                cancelled += 1
                report.append("  cancelled pending order {} ({})".format(
                    oid, o.get("ticker")))
            except Exception as e:
                report.append("  FAILED to cancel order {}: {}".format(oid, e))
    except Exception as e:
        report.append("  could not list pending orders: {}".format(e))
    return cancelled


def flatten_all(reason="manual panic flatten"):
    """Sell everything, cancel pending orders, email the summary. Returns report."""
    cfg = config.load()
    con = ledger.connect()
    report = ["=== PANIC FLATTEN {} ===".format(ledger.now())]

    cancelled = _cancel_pending_broker_orders(cfg, report)

    positions = ledger.open_positions(con)
    sold = []
    for p in positions:
        ticker, shares = p["ticker"], p["shares"]
        price = market.last_price(ticker) or p["avg_cost"]
        try:
            from bot import executor
            executor.execute(con, cfg, "sell", ticker, shares, price,
                             "[PANIC] {}".format(reason))
            sold.append("{} x{} @ ~${:.2f}".format(ticker, shares, price))
            report.append("  SOLD {} x{} @ ~${:.2f}".format(ticker, shares, price))
        except Exception as e:
            report.append("  FAILED to sell {}: {}".format(ticker, e))
    con.commit()

    cash = ledger.cash(con)
    con.close()
    report.append("flattened {} position(s), cancelled {} pending order(s), cash ${:,.2f}".format(
        len(sold), cancelled, cash))

    # summary email — always sent, so the button doubles as an email-path test
    notify.send_email(
        "🛑 PANIC FLATTEN — {} position(s) sold, {} order(s) cancelled".format(
            len(sold), cancelled),
        "\n".join(report) + "\n\nReason: {}\nMode: {} ({}), orders {}".format(
            reason, cfg.get("mode"),
            cfg.get("broker", {}).get("t212_environment", "demo"),
            "LIVE" if cfg.get("broker", {}).get("live_orders_enabled") else "dry-run"))

    try:
        from bot import dashboard
        dashboard.generate()
    except Exception:
        pass
    print("\n".join(report))
    return report


if __name__ == "__main__":
    flatten_all()
