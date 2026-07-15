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
    "gtrends_weight": 0.5,
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
    "gtrends": "gtrends_weight",
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
    """Guarded auto-tune (2026-07-15, per the exit-window study): tighten
    stop/TP toward the robust cell, but only BY ONE GRID NOTCH per run and
    only if the data supports it. Exits walk down gradually and reverse if
    the regime flips, instead of whiplashing to a recency-overfit cell."""
    import os
    from collections import defaultdict
    cfg = botconfig.load()
    if not cfg.get("learning", {}).get("auto_apply_tuning"):
        return "auto-tuning disabled"
    path = os.path.join(ROOT, "data", "tune_results.json")
    if not os.path.exists(path):
        return "no tune_results.json yet"
    rows = json.load(open(path))
    if not rows:
        return "empty tune results"

    STOP_GRID = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    TP_GRID = [15.0, 18.0, 20.0, 22.0, 25.0, 28.0]

    def step_toward(cur, target, grid):
        cur = min(grid, key=lambda g: abs(g - cur))
        tgt = min(grid, key=lambda g: abs(g - target))
        i, j = grid.index(cur), grid.index(tgt)
        if i == j:
            return cur
        return grid[i + (1 if j > i else -1)]

    groups = defaultdict(list)
    for r in rows:
        groups[(r["stop"], r["tp"])].append(r["return_pct"])
    ranked = sorted(groups.items(), key=lambda kv: min(kv[1]), reverse=True)
    (tgt_stop, tgt_tp), rets = ranked[0]
    tgt_stop = max(8.0, min(float(tgt_stop), 15.0))
    tgt_tp = max(15.0, min(float(tgt_tp), 28.0)) if tgt_tp < 900 else 28.0

    cur_stop = float(cfg["selling"]["trailing_stop_pct"])
    cur_tp = float(cfg["selling"]["take_profit_pct"])
    new_stop = step_toward(cur_stop, tgt_stop, STOP_GRID)
    new_tp = step_toward(cur_tp, tgt_tp, TP_GRID)

    bgroups = defaultdict(list)
    for r in rows:
        b = r.get("buys_wk")
        if b is not None:
            bgroups[int(b)].append(r["return_pct"])
    cur_buys = cfg["buying"].get("max_buys_per_week", 4)
    new_buys = cur_buys
    if bgroups:
        tgt_buys = max(4, min(sorted(bgroups.items(), key=lambda kv: min(kv[1]), reverse=True)[0][0] * 2, 8))
        new_buys = cur_buys + (1 if tgt_buys > cur_buys else -1 if tgt_buys < cur_buys else 0)
        new_buys = max(4, min(new_buys, 8))

    con = ledger.connect()
    changed = (new_stop, new_tp, new_buys) != (cur_stop, cur_tp, cur_buys)
    if changed:
        cfg["selling"]["trailing_stop_pct"] = new_stop
        cfg["selling"]["take_profit_pct"] = new_tp
        cfg["buying"]["max_buys_per_week"] = new_buys
        cfg["buying"]["max_buys_per_week_hc"] = new_buys * 2
        with open(os.path.join(ROOT, "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        msg = ("auto-tuned (1-notch, worst-case): stop {}->{}%, tp {}->{}%, buys/wk {}->{} (target {}/{}; worst-case {:+.1f}%)").format(
            cur_stop, new_stop, cur_tp, new_tp, cur_buys, new_buys, tgt_stop, tgt_tp, min(rets))
        ledger.log_decision(con, "auto_tune", msg)
        con.commit()
    else:
        msg = "auto-tune: already at robust target (stop {}%, tp {}%, buys/wk {})".format(cur_stop, cur_tp, cur_buys)
    con.close()
    print(msg)
    return msg


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "tune":
        auto_apply_tuning()
    else:
        adjust_weights()
