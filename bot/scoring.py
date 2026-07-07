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
        r_sc = reddit_score((reddit_data or {}).get(ticker))
        if r_sc:
            parts["reddit"] = round(r_sc * w.get("reddit_weight", 0.75), 2)
        from bot.signals.finnhub_data import insider_sentiment_bonus
        fh_sent = insider_sentiment_bonus(ticker)
        if fh_sent:
            parts["insider_sentiment"] = fh_sent
        if ticker in watchlist:
            parts["watchlist"] = 1.0
        bias = risk.sector_bias_bonus(research, info.get("sector"))
        if bias:
            parts["sector_bias"] = bias
        composite = sum(parts.values())
        results.append({
            "ticker": ticker,
            "score": round(composite, 2),
            "parts": {k: round(v, 2) for k, v in parts.items()},
            "price": snapshot.get(ticker, {}).get("price"),
            "sector": info.get("sector"),
            "name": info.get("shortName") or ticker,
            "insider_detail": ins,
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
