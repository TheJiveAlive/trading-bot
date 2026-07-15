"""Market-close summary — email 1 of the daily two (20:05 UTC weekdays).

Sends ONE branded digest: the day\'s trades + P/L + book, the latest overnight
learnings, and everything that was buffered (suppressed routine emails). Then
clears the buffer. The only other email is the pre-open plan (14:25 UK).
"""
import datetime as dt
import json
import os
import sqlite3

from bot import config, notify
from bot.config import DATA_DIR


def build():
    now = dt.datetime.now(dt.timezone.utc)
    L = ["## Market-close summary — {}".format(now.strftime("%A %d %B"))]

    # book + P/L
    try:
        b = json.load(open(os.path.join(DATA_DIR, "broker_state.json")))
        cash = b.get("cash") or {}
        L.append("**Book:** £{:.2f} · P/L £{:+.2f} · {} positions".format(
            cash.get("total", 0), cash.get("ppl", 0), len(b.get("positions", []))))
        for p in sorted(b.get("positions", []), key=lambda x: -(x.get("pnl") or 0)):
            L.append("- {} {:+.2f}".format(p["ticker"], p.get("pnl") or 0))
    except Exception:
        pass

    # today\'s trades
    try:
        con = sqlite3.connect(os.path.join(DATA_DIR, "ledger.db"))
        today = now.strftime("%Y-%m-%d")
        trades = con.execute("SELECT ts,side,ticker,shares,price FROM trades "
                             "WHERE ts>=? ORDER BY id", (today,)).fetchall()
        con.close()
        L.append("\n### Trades today ({})".format(len(trades)))
        for ts, side, tkr, sh, px in trades:
            L.append("- {} **{}** {} x{} @ ${:.2f}".format(
                ts[11:16], side.upper(), tkr, round(sh, 2), px))
        if not trades:
            L.append("- none — no candidate cleared the gauntlet")
    except Exception:
        pass

    # latest learnings section
    try:
        md = open(os.path.join(DATA_DIR, "learnings.md")).read()
        parts = md.split("\n## ")
        if len(parts) > 1:
            L.append("\n### Latest learnings\n## " + parts[-1][:1800])
    except Exception:
        pass

    # buffered (suppressed) emails
    dig_path = os.path.join(DATA_DIR, "email_digest.md")
    try:
        dig = open(dig_path).read().strip()
        if dig:
            L.append("\n### Also today (buffered alerts)\n" + dig[:2500])
    except Exception:
        pass

    return "[bot] Market-close summary · {}".format(now.strftime("%d %b")), "\n".join(L)


def main():
    config.load()
    subject, md = build()
    notify.send_email(subject, md, markdown=True, critical=True)  # bypass gate
    # clear the buffer now that it is flushed
    try:
        open(os.path.join(DATA_DIR, "email_digest.md"), "w").close()
    except Exception:
        pass
    print("close summary sent + digest cleared")


if __name__ == "__main__":
    main()
