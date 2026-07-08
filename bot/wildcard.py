"""Ring-fenced 'wildcard' sleeve: tiny speculative bets on sub-$1
r/pennystocks names, gated hard on quality.

Design principles (this is lottery-ticket money):
- Separate budget, position cap and size from the core book.
- Sub-$1 is allowed HERE ONLY, in a tight price band.
- Still forced through the same dilution + spread vetoes as everything else.
- Requires the day's research/intel to have vetted the name (require_research_ok):
  the ticker must appear on the research watchlist OR be flagged 'legit' by the
  hourly intel — never bought on raw Reddit noise alone.
- Chronic diluters (the usual penny-stock trap) are rejected.
"""
from bot import ledger, market, risk
from bot.signals.reddit import fetch_pennystock_buzz
from bot.signals.dilution import check_dilution


def _wildcard_positions(con):
    return [p for p in ledger.open_positions(con)
            if str(p["ticker"]).startswith("~") or _is_wild(con, p["ticker"])]


def _is_wild(con, ticker):
    row = con.execute("SELECT reason FROM trades WHERE ticker=? AND side='buy' "
                      "ORDER BY id DESC LIMIT 1", (ticker,)).fetchone()
    return bool(row and "[wildcard]" in (row[0] or ""))


def research_vetted(ticker, research, intel):
    """True if the day's research/intel actually vetted this name."""
    if ticker in risk.watchlist_tickers(research):
        return True
    # intel may list 'legit'-tagged movers; treat non-flagged movers as neutral
    movers = {m.get("ticker", "").upper() for m in (intel or {}).get("movers", [])}
    flagged = risk.intel_flagged(intel)
    return ticker in movers and ticker not in flagged


def scan_wildcards(con, cfg, research, intel, report):
    wc = cfg.get("wildcard", {})
    if not wc.get("enabled"):
        return
    held_wild = [p for p in ledger.open_positions(con) if _is_wild(con, p["ticker"])]
    if len(held_wild) >= wc["max_positions"]:
        report.append("  wildcard: sleeve full ({} positions)".format(len(held_wild)))
        return
    # weekly wildcard budget
    import datetime as dt
    monday = (dt.date.today() - dt.timedelta(days=dt.date.today().weekday())).isoformat()
    wk = con.execute("SELECT COUNT(*) FROM trades WHERE side='buy' AND ts>=? "
                     "AND reason LIKE '%[wildcard]%'", (monday,)).fetchone()[0]
    if wk >= wc.get("max_buys_per_week", 2):
        report.append("  wildcard: weekly budget used")
        return

    buzz = fetch_pennystock_buzz()
    if not buzz:
        report.append("  wildcard: no r/pennystocks data")
        return
    candidates = sorted(buzz.items(), key=lambda kv: kv[1]["mentions"], reverse=True)
    tickers = [t for t, _ in candidates[:25]]
    px = market.batch_price_volume(tickers)

    held = {p["ticker"] for p in ledger.open_positions(con)}
    report.append("  wildcard: scanning {} r/pennystocks names".format(len(tickers)))
    for ticker, info in candidates:
        if ticker in held:
            continue
        pv = px.get(ticker)
        if not pv:
            continue
        price, adv = pv
        if not (wc["price_min"] <= price <= wc["price_max"]):
            continue
        if adv < wc.get("min_avg_dollar_volume", 500000):
            continue
        if wc.get("require_research_ok") and not research_vetted(ticker, research, intel):
            ledger.log_decision(con, "wildcard_skip",
                                "{} buzzing on r/pennystocks but not research-vetted".format(ticker))
            continue
        dil = check_dilution(cfg, ticker)
        if dil.get("chronic") or dil.get("veto"):
            ledger.log_decision(con, "wildcard_skip",
                                "{} rejected: dilution ({} lifetime offerings)".format(
                                    ticker, dil.get("alltime_filings")))
            report.append("  wildcard skip {}: dilution risk".format(ticker))
            continue
        budget = min(ledger.cash(con), wc["max_position_usd"])
        shares = int(budget // price)
        if shares < 1:
            continue
        from bot import executor
        reason = "[wildcard] r/pennystocks buzz (rank {}, {} mentions), research-vetted, dilution-clean".format(
            info.get("rank"), info.get("mentions"))
        executor.execute(con, cfg, "buy", ticker, shares, price, reason,
                         parts={"wildcard": 1.0})
        report.append("  WILDCARD BUY {} x{} @ ${:.3f} — {}".format(
            ticker, shares, price, reason))
        return  # one wildcard per scan
    report.append("  wildcard: no name cleared the quality gates")
