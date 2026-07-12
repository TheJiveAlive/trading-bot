#!/usr/bin/env python3
"""CLI for the trading bot.

  python3 run.py scan        — run one full scan cycle (signals, exits, maybe buy)
  python3 run.py status      — show cash, positions, recent trades and decisions
  python3 run.py broker-sync — pull real Trading 212 account state (read-only)
"""
import sys

from bot import config, ledger, market


def status():
    config.load()
    con = ledger.connect()
    print("cash: ${:.2f}".format(ledger.cash(con)))
    print("\npositions:")
    positions = ledger.open_positions(con)
    if not positions:
        print("  (none)")
    for p in positions:
        price = market.last_price(p["ticker"]) or 0
        gain = (price / p["avg_cost"] - 1) * 100 if p["avg_cost"] else 0
        print("  {} x{} avg ${:.2f} now ${:.2f} ({:+.1f}%)".format(
            p["ticker"], p["shares"], p["avg_cost"], price, gain))
    print("\nlast 10 trades:")
    for r in con.execute("SELECT ts,side,ticker,shares,price,mode FROM trades "
                         "ORDER BY id DESC LIMIT 10"):
        print("  {} {} {} x{} @ ${:.2f} [{}]".format(*r))
    print("\nlast 10 decisions:")
    for r in con.execute("SELECT ts,kind,detail FROM decisions ORDER BY id DESC LIMIT 10"):
        print("  {} [{}] {}".format(r[0], r[1], r[2][:120]))
    con.close()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        from bot.scan import run_scan
        run_scan()
    elif cmd == "exits":
        from bot.scan import run_exits
        run_exits()
    elif cmd == "status":
        status()
    elif cmd == "broker-sync":
        from bot.broker_sync import sync
        s = sync(force=True)
        print("broker sync [{}]: {}".format("OK" if s["ok"] else "idle/err", s["detail"]))
    elif cmd == "dashboard":
        from bot.dashboard import generate
        try:
            print("wrote", generate()[0])
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("dashboard generation failed (non-fatal, likely transient data error):", e)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
