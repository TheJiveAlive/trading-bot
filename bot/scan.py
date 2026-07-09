"""One scan cycle: deposit check -> exit management -> signal scan -> buy."""
import datetime as dt
import json
import os

from bot import config, ledger, market, executor, risk
from bot.signals.insider import scan_insider_buys
from bot.signals.sector import sector_momentum_ranks
from bot.signals.news import news_score
from bot.signals.technicals import confluence_check, summarize
from bot.signals.reddit import fetch_mentions
from bot.scoring import score_candidates
from bot.config import LOG_DIR


def _is_wildcard(con, ticker):
    from bot.wildcard import _is_wild
    return _is_wild(con, ticker)


def manage_exits(con, cfg, research, report):
    sell_cfg = cfg["selling"]
    wc = cfg.get("wildcard", {})
    for pos in ledger.open_positions(con):
        price = market.last_price(pos["ticker"])
        if price is None:
            report.append("  ! no price for {}, skipping exit check".format(pos["ticker"]))
            continue
        ledger.update_high_water_mark(con, pos["ticker"], price)
        hwm = max(pos["high_water_mark"], price)
        gain_pct = (price / pos["avg_cost"] - 1) * 100
        dd_pct = (1 - price / hwm) * 100
        held_days = (dt.datetime.now(dt.timezone.utc)
                     - dt.datetime.fromisoformat(pos["opened_at"])).days

        # wildcard positions use their own wider stop/take-profit
        is_wc = _is_wildcard(con, pos["ticker"])
        if is_wc:
            stop_pct = wc.get("trailing_stop_pct", 20.0)
            take_profit = wc.get("take_profit_pct", 40.0)
        else:
            take_profit = sell_cfg["take_profit_pct"]
            pos_news = news_score(market.ticker_news(pos["ticker"]))
            if pos["ticker"] in risk.avoid_tickers(research):
                pos_news = min(pos_news, -1.0)  # research red flag: tightest stop
                report.append("  ! {} on research avoid list — stop tightened".format(
                    pos["ticker"]))
            stop_pct = risk.dynamic_stop_pct(cfg, pos_news, research)

        from bot.signals.catalysts import earnings_exit_due
        reason = None
        if not is_wc and earnings_exit_due(cfg, pos["ticker"]):
            reason = "pre-earnings exit: avoiding the binary print"
        elif dd_pct >= stop_pct and held_days >= sell_cfg["min_hold_days"]:
            reason = "trailing stop ({:.0f}%): {:.1f}% off high".format(stop_pct, dd_pct)
        elif gain_pct >= take_profit:
            reason = "take profit: +{:.1f}%".format(gain_pct)
        elif held_days > sell_cfg["max_hold_days"]:
            reason = "max hold {} days reached".format(sell_cfg["max_hold_days"])

        tag = "WC " if is_wc else ""
        if reason:
            executor.execute(con, cfg, "sell", pos["ticker"], pos["shares"], price, reason)
            report.append("  SELL {}{} x{} @ ${:.2f} — {}".format(
                tag, pos["ticker"], pos["shares"], price, reason))
        else:
            report.append("  hold {}{} x{} @ ${:.2f} ({:+.1f}%, {:.1f}% off high, stop {:.0f}%, day {})".format(
                tag, pos["ticker"], pos["shares"], price, gain_pct, dd_pct, stop_pct, held_days))


def maybe_buy(con, cfg, candidates, research, report, reddit_data=None):
    buy_cfg = cfg["buying"]
    threshold = risk.buy_threshold(cfg, research)
    avoid = risk.avoid_tickers(research)
    intel_flags = risk.intel_flagged(risk.load_intel())
    if intel_flags:
        report.append("  hourly intel flags (avoid this session): {}".format(
            ", ".join(sorted(intel_flags))))
    halted = risk.trading_halted(con, cfg)
    if halted:
        ledger.log_decision(con, "halt", halted)
        report.append("  BUYING HALTED: {}".format(halted))
        from bot import notify
        notify.send_email("[bot] BUYING HALTED", halted +
                          "\nExits continue to run. Buying resumes when equity recovers.")
        return
    # budgets: how many more buys allowed this scan
    week_left = buy_cfg["max_buys_per_week"] - ledger.buys_this_week(con)
    day_left = buy_cfg.get("max_buys_per_day", buy_cfg["max_buys_per_week"]) - ledger.buys_today(con)
    slots_left = buy_cfg["max_positions"] - len(ledger.open_positions(con))
    budget = min(week_left, day_left, slots_left)
    if budget <= 0:
        why = ("weekly cap" if week_left <= 0 else
               "daily cap" if day_left <= 0 else "max positions")
        ledger.log_decision(con, "skip_buy", "buy budget exhausted ({})".format(why))
        report.append("  no buy: {} reached".format(why))
        return

    bought = 0
    for c in candidates:
        if bought >= budget:
            report.append("  buy budget for this scan filled ({} trades)".format(bought))
            break
        if c["score"] < threshold:
            # candidates are score-sorted; nothing below will qualify either
            if bought == 0:
                report.append("  no buy: top score {} < {} (regime {})".format(
                    c["score"], threshold, risk.regime(research)))
            break
        held = {p["ticker"] for p in ledger.open_positions(con)}
        if c["ticker"] in avoid or c["ticker"] in intel_flags:
            ledger.log_decision(con, "skip_buy", "{} on avoid/intel list".format(c["ticker"]))
            continue
        if c["ticker"] in held or not c["price"]:
            continue
        if risk.sector_full(cfg, con, c.get("sector"), market):
            ledger.log_decision(con, "skip_buy",
                                "{}: max positions in {}".format(c["ticker"], c.get("sector")))
            continue
        available = ledger.cash(con)
        equity = available + sum(
            p["shares"] * (market.last_price(p["ticker"]) or p["avg_cost"])
            for p in ledger.open_positions(con))
        stop_pct = risk.dynamic_stop_pct(cfg, c["parts"].get("news", 0), research)
        shares = min(risk.position_size(cfg, equity, c["price"], stop_pct),
                     int(available // c["price"]))
        if shares < 1:
            ledger.log_decision(con, "skip_buy",
                                "{} sized to 0 shares (price ${:.2f}, cash ${:.2f})".format(
                                    c["ticker"], c["price"], available))
            continue
        ok, detail = confluence_check(
            cfg, c["ticker"], c["parts"].get("news", 0),
            reddit_info=(reddit_data or {}).get(c["ticker"]),
            n_insiders=c["insider_detail"].get("n_insiders", 0))
        if not ok:
            ledger.log_decision(con, "skip_buy", "{} failed confluence: {}".format(
                c["ticker"], summarize(detail)))
            report.append("  skip {}: confluence {}".format(c["ticker"], summarize(detail)))
            continue
        reason = ("score {} (parts {}); risk-sized {} sh at {:.0f}% stop; "
                  "confluence: {}").format(
            c["score"], c["parts"], shares, stop_pct, summarize(detail))
        executor.execute(con, cfg, "buy", c["ticker"], shares, c["price"], reason,
                         parts=c["parts"])
        report.append("  BUY {} x{} @ ${:.2f} — score {}".format(
            c["ticker"], shares, c["price"], c["score"]))
        bought += 1
    if bought == 0:
        report.append("  no buy: no candidate cleared all gates this scan")


def run_scan():
    cfg = config.load()
    con = ledger.connect()
    research = risk.load_research()
    report = ["=== scan {} (mode: {}) ===".format(ledger.now(), cfg["mode"])]

    from bot.signals.regime import quant_regime, blend_conservative
    q_regime, q_detail = quant_regime()
    if q_regime:
        report.append("  quant regime: {} (VIX {}, SPY>200dma: {}, credit rising: {})".format(
            q_regime, q_detail["vix"], q_detail["spy_above_200dma"],
            q_detail["credit_appetite_rising"]))
        blended = blend_conservative(risk.regime(research), q_regime)
        # FRED macro tilt (optional): a strongly negative tilt forces risk-off
        from bot.signals.macro import macro_signal
        tilt, mdetail = macro_signal()
        if mdetail:
            report.append("  FRED macro: {} (tilt {:+.2f})".format(mdetail, tilt))
            if tilt <= -0.5 and blended == "risk_on":
                blended = "neutral"
                report.append("  ! macro stress — risk_on downgraded to neutral")
        if blended != risk.regime(research):
            report.append("  ! regime overridden to {} (conservative blend)".format(blended))
        research = dict(research or {})
        research["market_regime"] = blended

    # force_regime overrides everything (full-auto mode); hard vetoes still apply
    forced = cfg.get("force_regime")
    if forced in ("risk_on", "neutral", "risk_off"):
        research = dict(research or {})
        research["market_regime"] = forced
        report.append("  force_regime={} (full-auto; hard vetoes still active)".format(forced))

    if research.get("_stale"):
        report.append("  ! research.json stale (from {}) — running neutral".format(
            research.get("date")))
        research = {k: v for k, v in research.items() if k == "market_regime"}
    elif research.get("date"):
        report.append("  research {} | regime: {} | watchlist: {}".format(
            research.get("date"), risk.regime(research),
            ", ".join(risk.watchlist_tickers(research)) or "(none)"))
    else:
        report.append("  no research.json — running neutral")

    if ledger.apply_monthly_deposit(con, cfg):
        report.append("  deposited ${:.2f}".format(cfg["monthly_deposit_usd"]))
    report.append("  cash: ${:.2f}".format(ledger.cash(con)))

    report.append("positions:")
    manage_exits(con, cfg, research, report)

    report.append("signals:")
    price_filter, snapshot = market.make_universe_filter(cfg)
    insider_hits = scan_insider_buys(cfg, price_filter)
    report.append("  insider buys in eligible universe: {}".format(len(insider_hits)))

    watchlist = risk.watchlist_tickers(research)
    extra = [t for t in watchlist if t not in insider_hits]
    if extra:
        eligible_extra = price_filter(extra)
        for t in eligible_extra:
            insider_hits[t] = {"total_usd": 0, "n_insiders": 0, "filings": 0}
        report.append("  watchlist candidates added: {}".format(
            ", ".join(sorted(eligible_extra)) or "(none eligible)"))

    sector_ranks = sector_momentum_ranks()
    top_sectors = sorted(sector_ranks, key=sector_ranks.get, reverse=True)[:3]
    report.append("  strongest sectors: {}".format(", ".join(top_sectors)))

    reddit_data = fetch_mentions()
    buzzing = [t for t in insider_hits if t in reddit_data]
    report.append("  reddit coverage: {} tickers tracked; buzzing candidates: {}".format(
        len(reddit_data), ", ".join(buzzing) or "(none)"))

    candidates = score_candidates(cfg, insider_hits, sector_ranks, snapshot,
                                  research=research, watchlist=watchlist,
                                  reddit_data=reddit_data)
    ledger.log_candidates(con, candidates)
    for c in candidates[:5]:
        report.append("  candidate {} ({}) score {} @ ${:.2f} {}".format(
            c["ticker"], c["name"], c["score"], c["price"] or 0, c["parts"]))

    report.append("action:")
    maybe_buy(con, cfg, candidates, research, report, reddit_data=reddit_data)

    # ring-fenced wildcard sleeve (sub-$1 r/pennystocks lottery tickets)
    if cfg.get("wildcard", {}).get("enabled") and not risk.trading_halted(con, cfg):
        report.append("wildcard sleeve:")
        try:
            from bot.wildcard import scan_wildcards
            scan_wildcards(con, cfg, research, risk.load_intel(), report)
        except Exception as e:
            report.append("  wildcard error (non-fatal): {}".format(e))

    con.commit()
    con.close()

    try:
        from bot import dashboard
        dashboard.generate()
        report.append("dashboard updated")
    except Exception as e:
        import traceback
        report.append("dashboard update failed (non-fatal): {}".format(e))
        traceback.print_exc()

    text = "\n".join(report)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(LOG_DIR, "scan_{}.log".format(stamp)), "w") as f:
        f.write(text + "\n")
    print(text)
    return text
