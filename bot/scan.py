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
    rgrades = risk.risk_flags(risk.load_risk())   # {TICKER: elevated|critical}
    intel_flags = risk.intel_flagged(risk.load_intel())   # intel's avoid-this-session set
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
            # ELEVATED risk-officer grade OR research avoid = tighten to the
            # tightest stop (elevated risk on a name we already hold).
            rgrade = rgrades.get(pos["ticker"])
            flagged = (rgrade == "elevated" or pos["ticker"] in risk.avoid_tickers(research)
                       or pos["ticker"] in intel_flags)
            if flagged:
                pos_news = min(pos_news, -1.0)
                why = rgrade or ("intel avoid" if pos["ticker"] in intel_flags
                                 else "research avoid")
                report.append("  ! {} flagged ({}) — stop tightened".format(
                    pos["ticker"], why))
            stop_pct = risk.dynamic_stop_pct(cfg, pos_news, research)

        # RSI overbought = momentum exhaustion → take profit sooner (sell-side
        # use of the same indicator that gates entries). Only when already green.
        eff_tp = take_profit
        rsi = None
        if held_days >= sell_cfg["min_hold_days"] and gain_pct > 5:
            from bot.signals.technicals import compute_metrics
            rsi = compute_metrics(pos["ticker"]).get("rsi")
            if rsi is not None and rsi >= 80:
                eff_tp = min(take_profit, max(gain_pct, 8))  # lock the gain in now

        # insider SELLING on a held name = bearish exit trigger (mirror signal)
        isell_exit = False
        if held_days >= sell_cfg["min_hold_days"] and not is_wc:
            from bot.signals.events import insider_selling
            if insider_selling(cfg, pos["ticker"]).get("total_usd", 0) >= 100000:
                isell_exit = True

        from bot.signals.catalysts import earnings_exit_due
        reason = None
        # CRITICAL risk-officer grade on a HELD name = exit at market, price-
        # blind (active offering/ATM, fraud, halt, delisting). Risk trumps P/L;
        # deliberately NOT a break-even target — that's the disposition trap.
        if not is_wc and rgrades.get(pos["ticker"]) == "critical":
            reason = "RISK EXIT: risk officer critical flag ({:+.1f}%)".format(gain_pct)
        elif not is_wc and earnings_exit_due(cfg, pos["ticker"]):
            reason = "pre-earnings exit: avoiding the binary print"
        elif isell_exit:
            reason = "insider selling — bearish tell, exiting"
        elif dd_pct >= stop_pct and held_days >= sell_cfg["min_hold_days"]:
            reason = "trailing stop ({:.0f}%): {:.1f}% off high".format(stop_pct, dd_pct)
        elif gain_pct >= eff_tp:
            reason = ("take profit: +{:.1f}%".format(gain_pct) +
                      (" (RSI {} overbought — locked in)".format(rsi) if eff_tp < take_profit else ""))
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
    # CONVICTION-AWARE caps: strong signals (score >= high_conviction_score)
    # earn the higher HC daily/weekly ceiling; routine ones use the base cap.
    # Candidates are score-sorted desc, so HC names are considered first, and a
    # cap hit means nothing lower will qualify either (safe to break).
    hc_score = buy_cfg.get("high_conviction_score", 999.0)
    if len(ledger.open_positions(con)) >= buy_cfg["max_positions"]:
        ledger.log_decision(con, "skip_buy", "max positions ({}) held".format(buy_cfg["max_positions"]))
        report.append("  no buy: max positions reached")
        return

    # DYNAMIC CAPS: regime + risk-officer stress + drawdown proximity move the
    # sector/day/week limits each scan instead of hand-set constants
    dyn = risk.dynamic_caps(cfg, con, research)
    report.append("  dynamic caps: sector {} · day {:+d} · week {:+d} ({})".format(
        dyn["sector_cap"] or "off", dyn["day_delta"], dyn["week_delta"], dyn["why"]))

    bought = 0
    for c in candidates:
        if c["score"] < threshold:
            # candidates are score-sorted; nothing below will qualify either
            if bought == 0:
                report.append("  no buy: top score {} < {} (regime {})".format(
                    c["score"], threshold, risk.regime(research)))
            break
        hc = c["score"] >= hc_score
        cap_day = (buy_cfg.get("max_buys_per_day_hc") if hc else None) \
            or buy_cfg.get("max_buys_per_day", buy_cfg["max_buys_per_week"])
        cap_week = (buy_cfg.get("max_buys_per_week_hc") if hc else None) \
            or buy_cfg["max_buys_per_week"]
        cap_day = max(1, cap_day + dyn["day_delta"])
        cap_week = max(1, cap_week + dyn["week_delta"])
        if (ledger.buys_today(con) >= cap_day
                or ledger.buys_this_week(con) >= cap_week
                or len(ledger.open_positions(con)) >= buy_cfg["max_positions"]):
            tier = "high-conviction" if hc else "normal"
            why = ("daily cap {}".format(cap_day) if ledger.buys_today(con) >= cap_day
                   else "weekly cap {}".format(cap_week) if ledger.buys_this_week(con) >= cap_week
                   else "max positions")
            ledger.log_decision(con, "skip_buy", "{} tier: {} reached".format(tier, why))
            report.append("  buy cap reached ({} tier — {})".format(tier, why))
            break
        held = {p["ticker"] for p in ledger.open_positions(con)}
        if c["ticker"] in avoid or c["ticker"] in intel_flags:
            ledger.log_decision(con, "skip_buy", "{} on avoid/intel list".format(c["ticker"]))
            continue
        if c["ticker"] in held or not c["price"]:
            continue
        if risk.sector_full(cfg, con, c.get("sector"), market, cap=dyn["sector_cap"]):
            ledger.log_decision(con, "skip_buy",
                                "{}: sector cap {} in {} ({})".format(
                                    c["ticker"], dyn["sector_cap"], c.get("sector"),
                                    risk.regime(research)))
            continue
        available = ledger.cash(con)
        equity = available + sum(
            p["shares"] * (market.last_price(p["ticker"]) or p["avg_cost"])
            for p in ledger.open_positions(con))
        stop_pct = risk.dynamic_stop_pct(cfg, c["parts"].get("news", 0), research)
        affordable = risk.qty(cfg, available / c["price"])
        shares = min(risk.position_size(cfg, equity, c["price"], stop_pct,
                                        conviction=hc), affordable)
        min_qty = 0.0001 if cfg.get("fractional_shares") else 1
        if shares < min_qty:
            ledger.log_decision(con, "skip_buy",
                                "{} sized to ~0 shares (price ${:.2f}, cash ${:.2f})".format(
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
        # RISK OFFICER VETO: critical flags (active offering/ATM, halt, fraud,
        # delisting, insider dumping) are absolute — no buy, whatever the score
        _rlvl = risk.risk_flags(risk.load_risk()).get(c["ticker"])
        if _rlvl == "critical":
            ledger.log_decision(con, "risk_veto", "{}: risk officer critical flag".format(
                c["ticker"]))
            report.append("  RISK VETO {}: critical flag from risk officer".format(
                c["ticker"]))
            continue
        # PRE-BUY CRITIC: Claude reviews this specific trade (fail-open)
        critic_note = ""
        from bot import critic as _critic
        if _critic.enabled(cfg):
            cand_ctx = dict(c, notional=shares * c["price"])
            try:
                from bot.signals.news_feed import _load_rolling
                heads = [h for h in _load_rolling() if h.get("ticker") == c["ticker"]]
            except Exception:
                heads = []
            approved, critic_note = _critic.review_buy(cfg, cand_ctx,
                                                       summarize(detail), heads)
            if not approved:
                ledger.log_decision(con, "critic_veto", "{}: {}".format(
                    c["ticker"], critic_note))
                report.append("  CRITIC VETO {}: {}".format(c["ticker"], critic_note))
                continue
            ledger.log_decision(con, "critic_ok", "{}: {}".format(
                c["ticker"], critic_note))
        cat = c.get("catalyst")
        reason = ("score {} (parts {}); risk-sized {} sh at {:.0f}% stop; "
                  "confluence: {}{}{}").format(
            c["score"], c["parts"], shares, stop_pct, summarize(detail),
            "; catalyst: " + cat if cat else "",
            "; " + critic_note if critic_note else "")
        executor.execute(con, cfg, "buy", c["ticker"], shares, c["price"], reason,
                         parts=c["parts"], catalyst=cat)
        report.append("  BUY {} x{} @ ${:.2f} — score {}{}".format(
            c["ticker"], shares, c["price"], c["score"],
            " [" + cat + "]" if cat else ""))
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


def run_exits():
    """Lightweight EXIT-ONLY cycle: check held positions against stops / targets
    / max-hold / pre-earnings and sell if triggered. No expensive insider scan.
    Cheap enough to run every price cycle (~60s) so stops fire promptly instead
    of only when a full scan happens to run."""
    cfg = config.load()
    con = ledger.connect()
    research = risk.load_research()
    # honour force_regime for the dynamic stop, same as a full scan
    forced = cfg.get("force_regime")
    if forced in ("risk_on", "neutral", "risk_off"):
        research = dict(research or {})
        research["market_regime"] = forced
    report = ["=== exits {} ===".format(ledger.now())]
    ledger.apply_monthly_deposit(con, cfg)
    manage_exits(con, cfg, research, report)
    equity = ledger.cash(con) + sum(
        p["shares"] * (market.last_price(p["ticker"]) or p["avg_cost"])
        for p in ledger.open_positions(con))
    ledger.record_equity(con, equity, ledger.cash(con))
    con.commit()
    con.close()
    try:
        from bot import dashboard
        dashboard.generate()
    except Exception as e:
        report.append("dashboard update failed: {}".format(e))
    print("\n".join(report))
    return "\n".join(report)
