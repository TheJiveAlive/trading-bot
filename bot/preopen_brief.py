"""Pre-open briefing — a 14:25 UK email projecting what the bot will do at the
bell. Reads the current book, regime, caps, cash and the freshest candidates
and writes a plain-English 'here's the plan' summary (branded markdown).

It PROJECTS, it does not trade — the session loop still makes the real calls a
few minutes later, so treat this as the morning outlook, not a guarantee.
"""
import datetime as dt
import json
import sqlite3

from bot import config, risk, market, ledger, notify


def _fmt_gbp(x):
    return "£{:,.2f}".format(x)


def build():
    cfg = config.load()
    try:
        research = json.load(open("data/research.json"))
    except Exception:
        research = {}
    try:
        broker = json.load(open("data/broker_state.json"))
    except Exception:
        broker = {}
    con = ledger.connect()
    now = dt.datetime.now(dt.timezone.utc)
    wk = now.isocalendar()[:2]

    # caps / cash
    buys = con.execute("SELECT ts FROM trades WHERE side='buy' "
                       "ORDER BY id DESC LIMIT 20").fetchall()
    today = sum(1 for (ts,) in buys if ts[:10] == now.strftime("%Y-%m-%d"))
    week = sum(1 for (ts,) in buys if dt.datetime.fromisoformat(
        ts.replace("Z", "+00:00")).isocalendar()[:2] == wk)
    dyn = risk.dynamic_caps(cfg, con, research)
    cap_day = max(1, cfg["buying"]["max_buys_per_day"] + dyn["day_delta"])
    cap_week = max(1, cfg["buying"]["max_buys_per_week"] + dyn["week_delta"])
    hc_day = cfg["buying"]["max_buys_per_day_hc"]
    cash = float(con.execute("SELECT value FROM meta WHERE key='cash'").fetchone()[0])
    slots = int(cash // cfg["buying"]["max_position_usd"])
    threshold = risk.buy_threshold(cfg, research)
    hc_score = cfg["buying"].get("high_conviction_score", 8.0)

    # book
    held = {p["ticker"]: p for p in broker.get("positions", [])}
    rgrades = risk.risk_flags(risk.load_risk())
    intel_flags = risk.intel_flagged(risk.load_intel())
    avoid = risk.avoid_tickers(research)

    # candidates (latest scan)
    last = con.execute("SELECT MAX(ts) FROM scan_candidates").fetchone()[0]
    cands = []
    if last:
        for t, s, d in con.execute(
                "SELECT ticker,score,detail FROM scan_candidates WHERE ts=? "
                "ORDER BY score DESC", (last,)):
            if t not in held:
                cands.append((t, s))
    con.close()

    # projection
    can_routine = today < cap_day and week < cap_week and slots > 0
    can_hc = today < hc_day and slots > 0
    targets = []
    for t, s in cands:
        if s < threshold:
            break  # score-sorted
        blocked = (t in avoid and "avoid-list") or (t in intel_flags and "intel-flag") \
            or (rgrades.get(t) == "critical" and "risk-critical")
        tier = "HC" if s >= hc_score else "routine"
        allowed = can_hc if tier == "HC" else can_routine
        targets.append((t, s, tier, blocked, allowed))

    # ---- compose ----
    L = []
    L.append("## Pre-open plan — {}".format(now.strftime("%A %d %B")))
    reg = research.get("market_regime", "unknown")
    L.append("**Market:** {} regime · buy line **{:.2f}** · US open 14:30 UK".format(
        reg, threshold))
    L.append("**Account:** {} · {} free (~{} new slot{})".format(
        _fmt_gbp(broker.get("cash", {}).get("total", 0)),
        _fmt_gbp(broker.get("cash", {}).get("free", 0)), slots,
        "" if slots == 1 else "s"))
    L.append("**Buy budget:** {}/{} today, {}/{} this week (HC lane {}/{})".format(
        today, cap_day, week, cap_week, today, hc_day))

    L.append("\n### Likely at the open")
    live = [x for x in targets if not x[3] and x[4]]
    if not can_routine and not can_hc:
        L.append("- 🅿️ **No new buys** — {}.".format(
            "cash used up" if slots == 0 else "daily/weekly budget spent"))
    elif live:
        for t, s, tier, _, _ in live[:5]:
            L.append("- 🎯 **BUY {}** (score {:.1f}, {} lane) — *if it still clears "
                     "confluence + critic at the scan*".format(t, s, tier))
    else:
        blocked = [x for x in targets if x[3]]
        if blocked:
            L.append("- ⏸️ Names above the line are all blocked: " +
                     ", ".join("{} ({})".format(t, b) for t, _, _, b, _ in blocked[:5]))
        else:
            L.append("- 👀 **Nothing above the {:.2f} line** — watching, no buy expected "
                     "unless scores lift at the open.".format(threshold))

    L.append("\n### The book ({} held)".format(len(held)))
    for t, p in sorted(held.items(), key=lambda kv: kv[1].get("pnl", 0)):
        pl = p.get("pnl", 0)
        flag = rgrades.get(t) or ("intel-flag" if t in intel_flags else None)
        leash = " · ⚠️ {} (tight leash)".format(flag) if flag else ""
        L.append("- **{}** {}{:.2f}{}".format(
            t, "+" if pl >= 0 else "−", abs(pl), leash))

    if cands:
        L.append("\n### On the radar (top non-held)")
        L.append(" · ".join("{} {:.1f}".format(t, s) for t, s in cands[:6]))

    L.append("\n*Projection from pre-open state — the session makes the real "
             "calls at ~14:30 UK through the full confluence + critic + risk gauntlet.*")
    subject = "[bot] Pre-open plan · {} · {} slot{}, {}".format(
        reg, slots, "" if slots == 1 else "s",
        "buys likely" if live else "watching")
    return subject, "\n".join(L)


def main():
    config.load()
    try:
        subject, md = build()
    except Exception as e:
        subject, md = "[bot] pre-open brief FAILED", "Error: {}".format(e)
    notify.send_email(subject, md, markdown=True)
    print("sent:", subject)


if __name__ == "__main__":
    main()
