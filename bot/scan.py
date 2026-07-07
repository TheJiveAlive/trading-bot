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


def manage_exits(con, cfg, research, report):
    sell_cfg = cfg["selling"]
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

        pos_news = news_score(market.ticker_news(pos["ticker"]))
        if pos["ticker"] in risk.avoid_tickers(research):
            pos_news = min(pos_news, -1.0)  # research red flag: tightest stop
            report.append("  ! {} on research avoid list — stop tightened".format(
                pos["ticker"]))
        stop_pct = risk.dynamic_stop_pct(cfg, pos_news, research)

        reason = None
        if dd_pct >= stop_pct and held_days >= sell_cfg["min_hold_days"]:
            reason = "trailing stop ({:.0f}%, news {:+.1f}): {:.1f}% off high".format(
                stop_pct, pos_news, dd_pct)
        elif gain_pct >= sell_cfg["take_profit_pct"]:
            reason = "take profit: +{:.1f}%".format(gain_pct)
        elif held_days > sell_cfg["max_hold_days"]:
            reason = "max hold {} days reached".format(sell_cfg["max_hold_days"])

        if reason:
            executor.execute(con, cfg, "sell", pos["ticker"], pos["shares"], price, reason)
            report.append("  SELL {} x{} @ ${:.2f} — {}".format(
                pos["ticker"], pos["shares"], price, reason))
        else:
            report.append("  hold {} x{} @ ${:.2f} ({:+.1f}%, {:.1f}% off high, stop {:.0f}%, day {})".format(
                pos["ticker"], pos["shares"], price, gain_pct, dd_pct, stop_pct, held_days))


def maybe_buy(con, cfg, candidates, research, report, reddit_data=None):
    buy_cfg = cfg["buying"]
    threshold = risk.buy_threshold(cfg, research)
    avoid = risk.avoid_tickers(research)
    if ledger.buys_this_week(con) >= buy_cfg["max_buys_per_week"]:
        ledger.log_decision(con, "skip_buy", "weekly buy budget already used")
        report.append("  no buy: weekly budget used")
        return
    if len(ledger.open_positions(con)) >= buy_cfg["max_positions"]:
        ledger.log_decision(con, "skip_buy", "max positions held")
        report.append("  no buy: max positions held")
        return
    available = ledger.cash(con)
    held = {p["ticker"] for p in ledger.open_positions(con)}
    for c in candidates:
        if c["score"] < threshold:
            ledger.log_decision(con, "skip_buy",
                                "top score {} below threshold {} (regime: {})".format(
                                    c["score"], threshold, risk.regime(research)))
            report.append("  no buy: top score {} < {} (regime {})".format(
                c["score"], threshold, risk.regime(research)))
            return
        if c["ticker"] in avoid:
            ledger.log_decision(con, "skip_buy",
                                "{} on research avoid list".format(c["ticker"]))
            continue
        if c["ticker"] in held or not c["price"]:
            continue
        budget = min(available, buy_cfg["max_position_usd"])
        shares = int(budget // c["price"])
        if shares < 1:
            ledger.log_decision(con, "skip_buy",
                                "{} scored {} but price ${:.2f} exceeds budget ${:.2f}".format(
                                    c["ticker"], c["score"], c["price"], budget))
            continue
        ok, detail = confluence_check(
            cfg, c["ticker"], c["parts"].get("news", 0),
            reddit_info=(reddit_data or {}).get(c["ticker"]),
            n_insiders=c["insider_detail"].get("n_insiders", 0))
        if not ok:
            ledger.log_decision(con, "skip_buy", "{} failed confluence: {}".format(
                c["ticker"], summarize(detail)))
            report.append("  skip {}: confluence {} ".format(
                c["ticker"], summarize(detail)))
            continue
        reason = "score {} (parts {}); confluence: {}; insiders: {}".format(
            c["score"], c["parts"], summarize(detail), c["insider_detail"])
        executor.execute(con, cfg, "buy", c["ticker"], shares, c["price"], reason)
        report.append("  BUY {} x{} @ ${:.2f} — {}".format(
            c["ticker"], shares, c["price"], reason))
        return
    report.append("  no buy: no affordable candidate above threshold")


def run_scan():
    cfg = config.load()
    con = ledger.connect()
    research = risk.load_research()
    report = ["=== scan {} (mode: {}) ===".format(ledger.now(), cfg["mode"])]

    if research.get("_stale"):
        report.append("  ! research.json stale (from {}) — running neutral".format(
            research.get("date")))
        research = {}
    elif research:
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

    con.commit()
    con.close()

    try:
        from bot import dashboard
        dashboard.generate()
        report.append("dashboard updated")
    except Exception as e:
        report.append("dashboard update failed: {}".format(e))

    text = "\n".join(report)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    with open(os.path.join(LOG_DIR, "scan_{}.log".format(stamp)), "w") as f:
        f.write(text + "\n")
    print(text)
    return text
