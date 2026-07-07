"""Adaptive risk: trailing stops move with news, and the daily research file
shifts the whole bot between risk-on / neutral / risk-off.

Stop band is clamped to 5–12%%: small-to-medium risk. Negative news on a held
position tightens its stop; a risk-off market regime tightens everything and
raises the bar for new buys.
"""
import datetime as dt
import json
import os

from bot.config import DATA_DIR

RESEARCH_PATH = os.path.join(DATA_DIR, "research.json")
RESEARCH_STALE_DAYS = 3
STOP_FLOOR = 5.0
STOP_CEIL = 12.0


def load_research():
    """Research dict, or {} when missing/stale (bot then runs neutral)."""
    if not os.path.exists(RESEARCH_PATH):
        return {}
    try:
        with open(RESEARCH_PATH) as f:
            r = json.load(f)
        date = dt.date.fromisoformat(r.get("date", "1970-01-01"))
        if (dt.date.today() - date).days > RESEARCH_STALE_DAYS:
            return {"_stale": True, "date": r.get("date")}
        return r
    except Exception:
        return {}


def regime(research):
    v = research.get("market_regime", "neutral")
    return v if v in ("risk_on", "neutral", "risk_off") else "neutral"


def dynamic_stop_pct(cfg, news_score, research):
    """Trailing stop %% for one position, given its news and the market regime."""
    stop = float(cfg["selling"]["trailing_stop_pct"])
    if news_score <= -1.0:
        stop = min(stop, 6.0)          # bad news: get out sooner
    elif news_score >= 1.0:
        stop += 2.0                     # good news: give it room to run
    if regime(research) == "risk_off":
        stop -= 2.0
    elif regime(research) == "risk_on":
        stop += 1.0
    return max(STOP_FLOOR, min(stop, STOP_CEIL))


def buy_threshold(cfg, research):
    base = float(cfg["buying"]["min_composite_score"])
    return base + {"risk_off": 1.0, "neutral": 0.0, "risk_on": -0.5}[regime(research)]


def sector_bias_bonus(research, sector):
    """-0.5..+0.5 score adjustment from research sector view."""
    if not sector:
        return 0.0
    bias = research.get("sector_bias", {}).get(sector, 0)
    try:
        return max(-1.0, min(float(bias), 1.0)) * 0.5
    except (TypeError, ValueError):
        return 0.0


def watchlist_tickers(research):
    return [w["ticker"].upper() for w in research.get("watchlist", [])
            if isinstance(w, dict) and w.get("ticker")]


def avoid_tickers(research):
    return {t.upper() for t in research.get("avoid", []) if isinstance(t, str)}
