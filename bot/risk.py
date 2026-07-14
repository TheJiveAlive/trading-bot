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
STOP_CEIL = 18.0   # raised 12->18 for vol-scaled stops: a 7%/day name needs a
                   # wider leash; risk-based sizing shrinks its position to match


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


def realized_vol_pct(ticker):
    """20-day close-to-close realized volatility as a DAILY %, from bars.db.
    None if insufficient history. (True ATR needs high/low we don't cache;
    close-to-close vol is the available, equivalent-in-spirit measure.)"""
    try:
        import math
        from bot import barcache
        c = barcache._con()
        rows = [r[0] for r in c.execute(
            "SELECT close FROM bars WHERE ticker=? ORDER BY date DESC LIMIT 21",
            (ticker,)).fetchall()]
        c.close()
        if len(rows) < 15:
            return None
        rows = rows[::-1]
        rets = [(rows[i] / rows[i - 1] - 1) for i in range(1, len(rows))
                if rows[i - 1] > 0]
        mu = sum(rets) / len(rets)
        return math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * 100
    except Exception:
        return None


def dynamic_stop_pct(cfg, news_score, research, ticker=None):
    """Trailing stop %% for one position. VOL-SCALED to the instrument first
    (a $2 mover needs a wider leash than a steady name or it noise-clips —
    2026-07-14), THEN adjusted for news + regime, THEN clamped with a
    VOL-AWARE FLOOR so a flagged high-vol name can't be crushed below its own
    daily noise. Position sizing is risk-based, so a wider stop auto-shrinks
    the position — dollar risk stays constant."""
    stop = float(cfg["selling"]["trailing_stop_pct"])
    rv = realized_vol_pct(ticker) if ticker else None
    # 1) scale to the stock's own volatility (~3.5%/day is a typical small-cap;
    #    calmer names tighten, wilder names widen), bounded 0.6–1.8x
    if rv is not None:
        stop *= max(0.6, min(rv / 3.5, 1.8))
    # 2) news + regime move it relative to that vol-appropriate base
    if news_score <= -1.0:
        stop *= 0.6                          # bad news / flagged: tighter leash
    elif news_score >= 1.0:
        stop += 2.0                          # good news: room to run
    if regime(research) == "risk_off":
        stop -= 2.0
    elif regime(research) == "risk_on":
        stop += 1.0
    # 3) floor at the greater of the absolute floor and ~1.5x daily vol — never
    #    tighter than the stock's own noise (this is what kills the 5% leash on
    #    a 7%/day name); clamp to the ceiling
    vol_floor = max(STOP_FLOOR, 1.5 * rv) if rv is not None else STOP_FLOOR
    return round(max(vol_floor, min(stop, STOP_CEIL)), 1)


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


def dynamic_caps(cfg, con, research):
    """DYNAMIC buy limits — the caps breathe with the data instead of being
    hand-set constants (user call 2026-07-14). Three AI/data inputs:

      1. regime (Claude's daily research):  risk_on / neutral / risk_off
      2. book stress (risk officer):        any CRITICAL-graded holding
      3. drawdown proximity:                equity within half the halt limit

    Returns {"sector_cap": int (0 = unlimited), "day_delta": int,
             "week_delta": int, "why": str}. Deltas are applied to the
    configured day/week caps (routine and high-conviction alike) and floored
    at 1. The nightly study session reviews whether this ladder helped and
    proposes notch changes — bounded learning, not config drift."""
    reg = regime(research or {})
    ladder = {"risk_on":  {"sector_cap": 0, "day_delta": +1, "week_delta": +2},
              "neutral":  {"sector_cap": 4, "day_delta": 0,  "week_delta": 0},
              "risk_off": {"sector_cap": 2, "day_delta": -1, "week_delta": -2}}
    out = dict(ladder[reg])
    why = ["regime {}".format(reg)]

    stressed = False
    rk = load_risk()
    crit = [t for t, v in (rk.get("holdings") or {}).items()
            if (v.get("risk") or "").lower() == "critical"]
    if crit:
        stressed = True
        why.append("risk officer: CRITICAL on {}".format(",".join(sorted(crit))))
    try:
        rows = con.execute("SELECT equity FROM equity_history "
                           "ORDER BY ts DESC LIMIT 30").fetchall()
        if rows:
            eq = rows[0][0]
            peak = max(r[0] for r in rows)
            dd = (1 - eq / peak) * 100 if peak > 0 else 0
            if dd >= cfg["risk"].get("drawdown_halt_pct", 12.0) / 2:
                stressed = True
                why.append("drawdown {:.1f}% (half of halt)".format(dd))
    except Exception:
        pass
    if stressed:   # one notch tighter whatever the regime says
        out["sector_cap"] = {0: 4, 4: 3, 2: 2}.get(out["sector_cap"], 2)
        out["day_delta"] -= 1
        out["week_delta"] -= 1
    out["why"] = ", ".join(why)
    return out


def sector_full(cfg, con, sector, market_module, cap=None):
    """True if we already hold `cap` positions in this sector. cap <= 0
    disables the check. cap=None falls back to config max_sector_positions
    (which dynamic_caps normally supplies at scan time)."""
    if cap is None:
        cap = int(cfg["risk"].get("max_sector_positions", 0))
    if not sector or cap <= 0:
        return False
    from bot import ledger
    count = 0
    for p in ledger.open_positions(con):
        info = market_module.ticker_info(p["ticker"])
        if info.get("sector") == sector:
            count += 1
    return count >= cap


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


RISK_PATH = os.path.join(DATA_DIR, "risk.json")
RISK_STALE_HOURS = 6


def load_risk():
    """Latest risk-officer dict, or {} if missing/stale (mirror of load_intel)."""
    if not os.path.exists(RISK_PATH):
        return {}
    try:
        with open(RISK_PATH) as f:
            rk = json.load(f)
        gen = rk.get("generated", "")
        if gen:
            when = dt.datetime.fromisoformat(gen.replace("Z", "+00:00"))
            age_h = (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600
            if age_h > RISK_STALE_HOURS:
                return {"_stale": True, "generated": gen}
        return rk
    except Exception:
        return {}


def risk_flags(rk):
    """{TICKER: "elevated"|"critical"} from the risk officer's flags list."""
    out = {}
    for f in (rk or {}).get("flags", []) or []:
        t = (f.get("ticker") or "").upper()
        lvl = (f.get("risk") or "").lower()
        if t and lvl in ("elevated", "critical"):
            out[t] = lvl
    return out
