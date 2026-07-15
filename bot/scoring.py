"""Composite candidate scoring: insider buys drive candidacy, then sector
momentum, fundamentals and news adjust the score."""
from bot.signals.insider import insider_score
from bot.signals.sector import sector_score
from bot.signals.fundamentals import fundamentals_score
from bot.signals.news import news_score
from bot.signals.reddit import reddit_score
from bot import market


def score_candidates(cfg, insider_hits, sector_ranks, snapshot, research=None,
                     watchlist=None, reddit_data=None):
    """Returns list of dicts sorted by composite score (desc).

    insider_hits entries with total_usd == 0 are watchlist-only candidates
    (from daily research) — they get a watchlist bonus instead of insider score.
    """
    from bot import risk
    research = research or {}
    watchlist = set(watchlist or [])
    w = cfg["signals"]
    # Claude's hourly intel conviction boosts ({ticker: 0.25..1.0}), flags excluded
    intel = risk.load_intel()
    flagged = risk.intel_flagged(intel)
    intel_boosts = {}
    for b in (intel or {}).get("conviction_boosts", []) or []:
        t = (b.get("ticker") or "").upper()
        if t and t not in flagged:
            try:
                intel_boosts[t] = max(0.0, min(float(b.get("boost", 0)), 1.0))
            except (TypeError, ValueError):
                pass
    # risk officer flags ({TICKER: elevated|critical}) — the bear's view
    rflags = risk.risk_flags(risk.load_risk())
    results = []
    for ticker, ins in insider_hits.items():
        info = market.ticker_info(ticker)
        news = market.ticker_news(ticker)
        parts = {
            "insider": (insider_score(ins) if ins.get("total_usd", 0) > 0 else 0.0) * w["insider_weight"],
            "sector": sector_score(info.get("sector"), sector_ranks) * w["sector_momentum_weight"],
            "fundamentals": fundamentals_score(info) * w["fundamentals_weight"],
            "news": news_score(news) * w["news_weight"],
        }
        from bot.signals.fundamentals_quant import piotroski_part
        pio = piotroski_part(ticker, w.get("piotroski_weight", 1.0))
        if pio:
            parts["piotroski"] = pio
        r_sc = reddit_score((reddit_data or {}).get(ticker))
        if r_sc:
            parts["reddit"] = round(r_sc * w.get("reddit_weight", 0.75), 2)
        from bot.signals.gtrends import trends_score
        g_sc = trends_score(ticker)
        if g_sc:
            parts["gtrends"] = round(g_sc * w.get("gtrends_weight", 0.5), 2)
        from bot.signals.trending import trending_score
        tr_sc = trending_score(ticker)
        if tr_sc:
            parts["trending"] = round(tr_sc * w.get("trending_weight", 0.5), 2)
            if r_sc:   # trending AND buzzing on Reddit = confirmed multi-platform attention
                parts["trending"] = round(parts["trending"] * 1.5, 2)
        from bot.signals.alphai import sentiment_bonus as alphai_sentiment
        ai_sc = alphai_sentiment(ticker)     # bidirectional -0.5..+0.5 (keyed)
        if ai_sc:
            parts["ai_news"] = round(ai_sc * w.get("alphai_weight", 1.0), 2)
        from bot.signals.finnhub_data import insider_sentiment_bonus, analyst_trend
        fh_sent = insider_sentiment_bonus(ticker)
        if fh_sent:
            parts["insider_sentiment"] = fh_sent
        at = analyst_trend(ticker)   # bidirectional: +buy consensus / −sell
        if at:
            parts["analyst_trend"] = at
        from bot.signals.catalysts import earnings_catalyst_score, breakout_score
        news_raw = news_score(news)
        ret5d = info.get("52WeekChange")  # coarse; refined in confluence
        e_sc, _ = earnings_catalyst_score(cfg, ticker,
                                          (info.get("regularMarketChangePercent") or 0), news_raw)
        if e_sc:
            parts["earnings"] = round(e_sc * w.get("earnings_weight", 1.0), 2)
        b_sc, _ = breakout_score(ticker)
        if b_sc:
            parts["breakout"] = round(b_sc * w.get("breakout_weight", 1.0), 2)
        from bot.signals.events import event_score
        ev_sc, ev_detail = event_score(cfg, ticker, company_name=info.get("shortName"))
        if ev_sc:
            parts["events"] = round(ev_sc * w.get("events_weight", 1.0), 2)
        if ticker in watchlist:
            parts["watchlist"] = 1.0
        # hourly Claude intel can BOOST conviction on fresh verified catalysts
        # (capped; vetoes still trump — a flagged ticker never gets here)
        iboost = intel_boosts.get(ticker)
        if iboost:
            parts["intel"] = round(min(iboost, 1.0) * w.get("intel_weight", 1.0), 2)
        # risk officer (offset 30-min agent): elevated risk drags the score;
        # critical additionally hard-vetoes the buy in scan.maybe_buy
        rlvl = rflags.get(ticker)
        if rlvl:
            parts["risk"] = -1.5 if rlvl == "elevated" else -3.0
        bias = risk.sector_bias_bonus(research, info.get("sector"))
        if bias:
            parts["sector_bias"] = bias
        composite = sum(parts.values())
        from bot.signals.news import classify_catalyst
        results.append({
            "ticker": ticker,
            "score": round(composite, 2),
            "parts": {k: round(v, 2) for k, v in parts.items()},
            "price": snapshot.get(ticker, {}).get("price"),
            "sector": info.get("sector"),
            "name": info.get("shortName") or ticker,
            "insider_detail": ins,
            "catalyst": classify_catalyst(news),   # news training marker
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
