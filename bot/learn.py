"""Bounded reward learning: nudge signal weights toward what actually made
money, slowly and within hard limits.

This is deliberately NOT deep reinforcement learning. With a few dozen trades
a year, a neural policy would memorize noise. Instead: each closed trade pays
its P/L back to the signals that drove the entry (signal_rewards table); once
a signal has enough evidence, its weight drifts ±nudge_pct per adjustment,
clamped to [floor_x, ceil_x] × the hand-set default. Hard vetoes and risk
caps are never touched by learning.

Run monthly (review_task.sh gates it to the first Sunday).
"""
import json
import os

from bot import config as botconfig
from bot import ledger, notify
from bot.config import ROOT

# hand-set defaults = anchor points learning may not drift far from
DEFAULTS = {
    "insider_weight": 2.0,
    "sector_momentum_weight": 1.0,
    "fundamentals_weight": 1.5,
    "news_weight": 1.0,
    "reddit_weight": 0.75,
    "trending_weight": 0.5,
    "alphai_weight": 1.0,
    "intel_weight": 1.0,
}
PART_TO_WEIGHT = {
    "insider": "insider_weight",
    "sector": "sector_momentum_weight",
    "fundamentals": "fundamentals_weight",
    "news": "news_weight",
    "reddit": "reddit_weight",
    "trending": "trending_weight",
    "ai_news": "alphai_weight",
    "intel": "intel_weight",
}


def signal_report(con, min_trades):
    """{signal: {'trades': n, 'avg_pnl_pct': x}} for signals that contributed
    meaningfully (>0.2 score) to closed trades."""
    out = {}
    rows = con.execute(
        "SELECT signal, COUNT(*), AVG(pnl_pct) FROM signal_rewards "
        "WHERE contribution > 0.2 GROUP BY signal").fetchall()
    for signal, n, avg in rows:
        out[signal] = {"trades": n, "avg_pnl_pct": round(avg, 2),
                       "enough_evidence": n >= min_trades}
    return out


def adjust_weights():
    cfg = botconfig.load()
    lc = cfg["learning"]
    if not lc.get("enabled"):
        return "learning disabled"
    con = ledger.connect()
    report = signal_report(con, lc["min_trades_per_signal"])

    changes = []
    for part, wkey in PART_TO_WEIGHT.items():
        stats = report.get(part)
        if not stats or not stats["enough_evidence"]:
            continue
        current = cfg["signals"][wkey]
        default = DEFAULTS[wkey]
        step = default * lc["nudge_pct"] / 100.0
        if stats["avg_pnl_pct"] > 2.0:
            proposed = current + step
        elif stats["avg_pnl_pct"] < -2.0:
            proposed = current - step
        else:
            continue
        lo, hi = default * lc["weight_floor_x"], default * lc["weight_ceil_x"]
        proposed = round(max(lo, min(proposed, hi)), 3)
        if proposed != current:
            cfg["signals"][wkey] = proposed
            changes.append("{}: {} -> {} (avg P/L {:+.1f}% over {} trades)".format(
                wkey, current, proposed, stats["avg_pnl_pct"], stats["trades"]))

    if changes:
        with open(os.path.join(ROOT, "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        for c in changes:
            ledger.log_decision(con, "learning", c)
        con.commit()
        notify.send_email(
            "[bot learning] {} weight adjustment(s)".format(len(changes)),
            "Signal performance (closed trades):\n{}\n\nApplied (bounded {}%-{}% of defaults):\n{}".format(
                json.dumps(report, indent=2),
                int(lc["weight_floor_x"] * 100), int(lc["weight_ceil_x"] * 100),
                "\n".join(changes)))
        result = "adjusted: " + "; ".join(changes)
    else:
        result = "no adjustments (insufficient evidence or performance within band)"
        ledger.log_decision(con, "learning", result)
        con.commit()
    con.close()
    print(result)
    return result


def auto_apply_tuning():
    """When learning.auto_apply_tuning is on, pick the best ROBUST stop/take-profit
    region from the tune sweep and apply it to config, clamped to safe bounds.
    Robust = the parameter whose neighbourhood also performs well, not the single
    lucky top row. Never touches hard vetoes or position caps."""
    import os
    cfg = botconfig.load()
    if not cfg.get("learning", {}).get("auto_apply_tuning"):
        return "auto-tuning disabled"
    path = os.path.join(ROOT, "data", "tune_results.json")
    if not os.path.exists(path):
        return "no tune_results.json yet"
    rows = json.load(open(path))
    if not rows:
        return "empty tune results"
    # group by (stop, tp); score each by MEDIAN return across its variants
    from collections import defaultdict
    import statistics
    groups = defaultdict(list)
    for r in rows:
        groups[(r["stop"], r["tp"])].append(r["return_pct"])
    ranked = sorted(groups.items(), key=lambda kv: statistics.median(kv[1]), reverse=True)
    (best_stop, best_tp), rets = ranked[0]
    # clamp to safe bounds
    best_stop = max(8.0, min(float(best_stop), 15.0))
    best_tp = max(15.0, min(float(best_tp), 40.0)) if best_tp < 900 else 40.0

    con = ledger.connect()
    old = (cfg["selling"]["trailing_stop_pct"], cfg["selling"]["take_profit_pct"])
    if (best_stop, best_tp) != old:
        cfg["selling"]["trailing_stop_pct"] = best_stop
        cfg["selling"]["take_profit_pct"] = best_tp
        with open(os.path.join(ROOT, "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        msg = "auto-tuned exits: stop {}->{}%, take-profit {}->{}% (robust median return {:+.1f}%)".format(
            old[0], best_stop, old[1], best_tp, statistics.median(rets))
        ledger.log_decision(con, "auto_tune", msg)
        con.commit()
    else:
        msg = "auto-tune: current exits already optimal (stop {}%, tp {}%)".format(*old)
    con.close()
    print(msg)
    return msg


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "tune":
        auto_apply_tuning()
    else:
        adjust_weights()
