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


def qty(cfg, raw):
    """Round a share quantity per the fractional/whole-share setting. Fractional
    → 4dp (Trading 212 supports decimals); whole → floor to integer."""
    if cfg.get("fractional_shares"):
        return round(max(0.0, raw), 4)
    return float(int(max(0.0, raw)))


def position_size(cfg, equity, price, stop_pct, conviction=False):
    """Shares sized so hitting the stop loses ~risk_per_trade_pct of equity
    (volatility-aware), capped by max_position_usd. Fractional when enabled.
    conviction=True (score >= buying.high_conviction_score) risks
    risk_per_trade_pct_hc instead — strong evidence earns more capital; the
    max_position_usd cap still applies to every trade."""
    r = cfg["risk"]
    risk_pct = (r.get("risk_per_trade_pct_hc", r["risk_per_trade_pct"])
                if conviction else r["risk_per_trade_pct"])
    risk_budget = equity * risk_pct / 100.0
    per_share_risk = price * stop_pct / 100.0
    if per_share_risk <= 0:
        return 0
    shares_by_risk = risk_budget / per_share_risk
    shares_by_cap = cfg["buying"]["max_position_usd"] / price
    return qty(cfg, min(shares_by_risk, shares_by_cap))


def trading_halted(con, cfg):
    """Reason string if buying should halt (drawdown/daily-loss circuit
    breaker), else None. Sells are never halted — exits always run."""
    rows = con.execute("SELECT ts, equity FROM equity_history ORDER BY id").fetchall()
    if len(rows) < 2:
        return None
    peak = max(e for _, e in rows)
    latest = rows[-1][1]
    dd = (1 - latest / peak) * 100 if peak else 0
    if dd >= cfg["risk"]["drawdown_halt_pct"]:
        return "drawdown circuit breaker: {:.1f}% below peak (limit {}%)".format(
            dd, cfg["risk"]["drawdown_halt_pct"])
    today = dt.date.today().isoformat()
    todays = [e for ts, e in rows if ts[:10] == today]
    if len(todays) >= 2:
        day_loss = (1 - todays[-1] / todays[0]) * 100
        if day_loss >= cfg["risk"]["daily_loss_halt_pct"]:
            return "daily-loss circuit breaker: -{:.1f}% today (limit {}%)".format(
                day_loss, cfg["risk"]["daily_loss_halt_pct"])
    return None


def sector_full(cfg, con, sector, market_module):
    """True if we already hold max_sector_positions in this sector."""
    if not sector:
        return False
    from bot import ledger
    count = 0
    for p in ledger.open_positions(con):
        info = market_module.ticker_info(p["ticker"])
        if info.get("sector") == sector:
            count += 1
    return count >= cfg["risk"]["max_sector_positions"]


def watchlist_tickers(research):
    return [w["ticker"].upper() for w in research.get("watchlist", [])
            if isinstance(w, dict) and w.get("ticker")]


def avoid_tickers(research):
    return {t.upper() for t in research.get("avoid", []) if isinstance(t, str)}


INTEL_PATH = os.path.join(DATA_DIR, "intel.json")
INTEL_STALE_HOURS = 4


def load_intel():
    """Latest hourly intel dict, or {} if missing/stale."""
    if not os.path.exists(INTEL_PATH):
        return {}
    try:
        with open(INTEL_PATH) as f:
            intel = json.load(f)
        gen = intel.get("generated", "")
        if gen:
            when = dt.datetime.fromisoformat(gen.replace("Z", "+00:00"))
            age_h = (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600
            if age_h > INTEL_STALE_HOURS:
                return {"_stale": True, "generated": gen}
        return intel
    except Exception:
        return {}


def intel_flagged(intel):
    """Tickers the hourly intel says to avoid buying this session."""
    return {t.upper() for t in (intel or {}).get("flags_for_bot", [])
            if isinstance(t, str)}
