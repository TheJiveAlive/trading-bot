#!/usr/bin/env python3
"""Backtest the core insider+momentum strategy over historical data.

    python3 backtest.py --months 4

Replays: SEC Form 4 open-market purchases (from EDGAR daily indexes),
price/liquidity filtering, momentum checks, weekly whole-share buys from a
$127/month budget, trailing-stop/take-profit/max-hold exits.

Cannot replay (data doesn't exist historically on free sources): news
sentiment, intraday VWAP/RVOL, bid-ask spreads, options IV, the daily research
layer. Fills are at daily close with no spread cost. CIK->ticker mapping is
current-day, so companies delisted since then vanish (survivorship bias).
Treat results as OPTIMISTIC.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import warnings
import xml.etree.ElementTree as ET

warnings.filterwarnings("ignore")

import requests
import yfinance as yf

from bot import config as botconfig
from bot.config import CACHE_DIR, DATA_DIR
from bot.market import SECTOR_ETFS
from bot.signals.insider import cik_to_ticker_map, insider_score

SEC_DELAY = 0.12
DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{ymd}.idx"


def sec_session(cfg):
    s = requests.Session()
    s.headers.update({"User-Agent": cfg["edgar_user_agent"]})
    return s


# ---------- phase 1: collect Form 4 events from daily indexes ----------

def collect_events(sess, cikmap, start, end):
    """[(date_iso, ticker, cik, path)] for Form 4 filings whose filer CIK maps
    to a listed ticker (i.e. the issuer row of the filing)."""
    cache = os.path.join(CACHE_DIR, "bt_events_{}_{}.json".format(start, end))
    if os.path.exists(cache):
        with open(cache) as f:
            return [tuple(e) for e in json.load(f)]
    events, seen = [], set()
    day = start
    while day <= end:
        if day.weekday() < 5:
            url = DAILY_INDEX.format(y=day.year, q=(day.month - 1) // 3 + 1,
                                     ymd=day.strftime("%Y%m%d"))
            r = sess.get(url, timeout=30)
            time.sleep(SEC_DELAY)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    if not line.startswith("4 ") and not line.startswith("4/A"):
                        continue
                    if line.startswith("4/A"):
                        continue  # amendments: skip to avoid double counting
                    parts = re.split(r"\s{2,}", line.strip())
                    if len(parts) < 5:
                        continue
                    try:
                        cik = int(parts[2])
                    except ValueError:
                        continue
                    ticker = cikmap.get(cik)
                    path = parts[4]
                    if ticker and (ticker, path) not in seen:
                        seen.add((ticker, path))
                        events.append((day.isoformat(), ticker, cik, path))
        day += dt.timedelta(days=1)
    with open(cache, "w") as f:
        json.dump(events, f)
    return events


# ---------- phase 2: price history for all involved tickers ----------

def download_history(tickers, start, end):
    """{ticker: DataFrame(Close, Volume)} covering [start-40d, end].
    Uses Alpaca historical bars when configured (fast, no throttle); falls back
    to Yahoo for any gaps."""
    hist = {}
    t0 = (start - dt.timedelta(days=60)).isoformat()
    t1 = (end + dt.timedelta(days=2)).isoformat()

    try:
        from bot import alpaca
        if alpaca.configured():
            print("  fetching history via Alpaca (fast path)...", flush=True)
            hist = alpaca.historical_bars(tickers, t0, t1)
            print("  Alpaca returned {}/{} tickers".format(len(hist), len(tickers)), flush=True)
            missing = [t for t in tickers if t not in hist]
            if not missing:
                return hist
            print("  filling {} gaps via Yahoo...".format(len(missing)), flush=True)
            tickers = missing
    except Exception as e:
        print("  Alpaca history unavailable ({}), using Yahoo".format(e), flush=True)

    for i in range(0, len(tickers), 200):
        chunk = tickers[i:i + 200]
        df = yf.download(chunk, start=t0, end=t1, interval="1d", progress=False,
                         group_by="ticker", threads=True, auto_adjust=True)
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                sub = df[t] if len(chunk) > 1 else df
                sub = sub[["Close", "Volume"]].dropna()
                if len(sub) >= 25:
                    hist[t] = sub
            except Exception:
                continue
        print("  history: {}/{} tickers".format(len(hist), len(tickers)), flush=True)
        time.sleep(1)
    return hist


def asof(df, date_iso, col="Close"):
    """Last value at or before date; None if unavailable."""
    sub = df[df.index.strftime("%Y-%m-%d") <= date_iso]
    return float(sub[col].iloc[-1]) if len(sub) else None


def metrics_asof(df, date_iso):
    """(price, adv20, ret5d, above_ma20, ext_pct) as of date."""
    sub = df[df.index.strftime("%Y-%m-%d") <= date_iso]
    if len(sub) < 21:
        return None
    c, v = sub["Close"], sub["Volume"]
    price = float(c.iloc[-1])
    adv = float((c.iloc[-20:] * v.iloc[-20:]).mean())
    ret5d = price / float(c.iloc[-6]) - 1
    ma20 = float(c.iloc[-20:].mean())
    return price, adv, ret5d, price > ma20, (price / ma20 - 1) * 100


# ---------- phase 3: parse filings for qualifying purchases ----------

PURCHASE_CACHE = os.path.join(CACHE_DIR, "bt_purchases.json")


def load_purchase_cache():
    if os.path.exists(PURCHASE_CACHE):
        with open(PURCHASE_CACHE) as f:
            return json.load(f)
    return {}


def save_purchase_cache(cache):
    with open(PURCHASE_CACHE, "w") as f:
        json.dump(cache, f)


def parse_txt_form4(sess, path):
    """(owner, total_purchase_usd) from a full-submission .txt, or None."""
    url = "https://www.sec.gov/Archives/" + path
    try:
        r = sess.get(url, timeout=30)
        time.sleep(SEC_DELAY)
        if r.status_code != 200:
            return None
        m = re.search(r"<XML>(.*?)</XML>", r.text, re.S)
        if not m:
            return None
        root = ET.fromstring(m.group(1).strip())
    except Exception:
        return None
    if root.tag != "ownershipDocument":
        return None
    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or "?"
    total = 0.0
    for txn in root.iter("nonDerivativeTransaction"):
        code = txn.findtext(".//transactionCoding/transactionCode")
        acq = txn.findtext(".//transactionAcquiredDisposedCode/value")
        if code != "P" or acq != "A":
            continue
        try:
            shares = float(txn.findtext(".//transactionShares/value") or 0)
            price = float(txn.findtext(".//transactionPricePerShare/value") or 0)
            total += shares * price
        except (TypeError, ValueError):
            continue
    return (owner, total) if total > 0 else None


# ---------- phase 4: simulation ----------

def _spread_fill(side, price):
    """Realistic fill: pay the estimated spread (thinner/cheaper = wider). This
    is the single biggest reason paper/backtest results overstate live P/L on
    small-caps. Estimates: <$1 = 4%, <$5 = 2%, else 0.8%."""
    est = 0.04 if price < 1 else (0.02 if price < 5 else 0.008)
    return price * (1 + est / 2) if side == "buy" else price * (1 - est / 2)


def simulate(cfg, weekly_candidates, hist, trading_days, start, progress=False):
    buy_cfg, sell_cfg = cfg["buying"], cfg["selling"]
    cash, positions, trades = 0.0, {}, []
    equity_curve = []
    last_deposit_month, last_buy_week = None, None
    total_weeks = len({d.isocalendar()[:2] for d in trading_days}) or 1
    seen_weeks, last_prog_week = set(), None

    for day in trading_days:
        d = day.strftime("%Y-%m-%d")
        month = d[:7]
        if month != last_deposit_month:
            cash += cfg["monthly_deposit_usd"]
            last_deposit_month = month

        # exits at close
        for tkr in list(positions):
            p = positions[tkr]
            price = asof(hist[tkr], d)
            if price is None:
                continue
            p["hwm"] = max(p["hwm"], price)
            held = (day.date() - p["opened"]).days
            gain = (price / p["cost"] - 1) * 100
            dd = (1 - price / p["hwm"]) * 100
            reason = None
            if dd >= sell_cfg["trailing_stop_pct"] and held >= sell_cfg["min_hold_days"]:
                reason = "stop"
            elif gain >= sell_cfg["take_profit_pct"]:
                reason = "take_profit"
            elif held > sell_cfg["max_hold_days"]:
                reason = "max_hold"
            if reason:
                fill = _spread_fill("sell", price)   # sell at the bid
                cash += p["shares"] * fill
                trades.append({"ticker": tkr, "in": p["opened"].isoformat(),
                               "out": d, "buy": p["cost"], "sell": fill,
                               "shares": p["shares"],
                               "pct": round((fill / p["cost"] - 1) * 100, 1),
                               "usd": round((fill - p["cost"]) * p["shares"], 2),
                               "exit": reason})
                del positions[tkr]

        # weekly buys (up to max_buys_per_week, one per day)
        week = day.isocalendar()[:2]
        if week != last_buy_week:
            buys_this_week = 0
            last_buy_week = week
        if buys_this_week < buy_cfg["max_buys_per_week"] and len(positions) < buy_cfg["max_positions"]:
            cands = weekly_candidates.get(week, [])
            cands = sorted(cands, key=lambda c: c["score"], reverse=True)
            for c in cands:
                if c["ticker"] in positions or c["ticker"] not in hist:
                    continue
                price = asof(hist[c["ticker"]], d)
                if price is None or price < 0.5:
                    continue
                fill = _spread_fill("buy", price)   # buy at the ask
                budget = min(cash, buy_cfg["max_position_usd"])
                shares = int(budget // fill)
                if shares < 1:
                    continue
                cash -= shares * fill
                positions[c["ticker"]] = {"shares": shares, "cost": fill,
                                          "hwm": fill, "opened": day.date(),
                                          "score": c["score"]}
                buys_this_week += 1
                break

        pos_val = sum(p["shares"] * (asof(hist[t], d) or p["cost"])
                      for t, p in positions.items())
        equity_curve.append((d, round(cash + pos_val, 2)))

        if progress:
            wk = day.isocalendar()[:2]
            if wk != last_prog_week:
                last_prog_week = wk
                seen_weeks.add(wk)
                print("  wk {:>2}/{}  {}  equity ${:>10,.2f}  {} open  {} trades".format(
                    len(seen_weeks), total_weeks, d, cash + pos_val,
                    len(positions), len(trades)), flush=True)

    # value open positions at final close
    final_open = [{"ticker": t, "shares": p["shares"], "cost": p["cost"],
                   "now": asof(hist[t], trading_days[-1].strftime("%Y-%m-%d"))}
                  for t, p in positions.items()]
    return cash, positions, trades, equity_curve, final_open


def tune(cfg, start, end):
    """Sweep exit/entry parameters over cached candidates from a prior full
    run. Fast: no SEC fetching, price history only for candidate tickers."""
    cand_cache = os.path.join(CACHE_DIR, "bt_candidates_{}_{}.json".format(start, end))
    if not os.path.exists(cand_cache):
        print("no candidate cache for {} -> {}; run the full backtest first "
              "(same --months value)".format(start, end))
        sys.exit(1)
    with open(cand_cache) as f:
        raw = json.load(f)
    weekly = {}
    for k, v in raw.items():
        y, w = k.rsplit("-", 1)
        weekly[(int(y), int(w))] = v

    tickers = sorted({c["ticker"] for v in weekly.values() for c in v})
    print("tune: {} candidate tickers across {} weeks".format(len(tickers), len(weekly)))
    hist = download_history(tickers, start, end)
    spy = yf.download("SPY", start=start.isoformat(),
                      end=(end + dt.timedelta(days=1)).isoformat(),
                      interval="1d", progress=False, auto_adjust=True)
    trading_days = list(spy.index.to_pydatetime())

    import copy
    rows = []
    for stop in (8.0, 10.0, 12.0, 15.0):
        for tp in (15.0, 20.0, 25.0, 30.0, 999.0):  # 999 = never take profit, ride the stop
            for buys in (1, 2, 3, 4):  # extended per learnings — validate the live 4/wk cap
                for min_score in (4.5, 5.0, 5.5, 6.0):  # finer steps where the threshold actually cuts
                    c = copy.deepcopy(cfg)
                    c["selling"]["trailing_stop_pct"] = stop
                    c["selling"]["take_profit_pct"] = tp
                    c["buying"]["max_buys_per_week"] = buys
                    wk = {k: [x for x in v if x["score"] >= min_score]
                          for k, v in weekly.items()}
                    cash, positions, trades, curve, final_open = simulate(
                        c, wk, hist, trading_days, start)
                    open_val = sum((p["now"] or p["cost"]) * p["shares"] for p in final_open)
                    eq = cash + open_val
                    deposited = c["monthly_deposit_usd"] * len({d[:7] for d, _ in curve})
                    peak, maxdd = 0.0, 0.0
                    for _, e in curve:
                        peak = max(peak, e)
                        if peak > 0:
                            maxdd = max(maxdd, (1 - e / peak) * 100)
                    wins = sum(1 for t in trades if t["usd"] > 0)
                    rows.append({
                        "stop": stop, "tp": tp, "buys_wk": buys, "min_score": min_score,
                        "trades": len(trades),
                        "win_rate": round(100 * wins / len(trades), 0) if trades else None,
                        "return_pct": round((eq / deposited - 1) * 100, 1),
                        "max_dd_pct": round(maxdd, 1),
                    })
    rows.sort(key=lambda r: r["return_pct"], reverse=True)
    print("\n{:>5} {:>5} {:>8} {:>10} {:>7} {:>9} {:>11} {:>10}".format(
        "stop", "tp", "buys/wk", "min_score", "trades", "win_rate", "return_pct", "max_dd"))
    for r in rows:
        print("{stop:>5} {tp:>5} {buys_wk:>8} {min_score:>10} {trades:>7} "
              "{win_rate!s:>9} {return_pct:>11} {max_dd_pct:>10}".format(**r))
    with open(os.path.join(DATA_DIR, "tune_results.json"), "w") as f:
        json.dump(rows, f, indent=2)
    print("\nsaved: data/tune_results.json — remember these are close-fill, "
          "zero-spread numbers; prefer robust regions over the single top row.")


def _load_candidate_cache():
    """Newest bt_candidates cache -> (weekly dict keyed by (year,week), start, end)."""
    import glob
    caches = sorted(glob.glob(os.path.join(CACHE_DIR, "bt_candidates_*.json")))
    if not caches:
        print("no candidate cache — run a full backtest first")
        sys.exit(1)
    path = caches[-1]
    m = re.search(r"bt_candidates_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", path)
    start, end = dt.date.fromisoformat(m.group(1)), dt.date.fromisoformat(m.group(2))
    with open(path) as f:
        raw = json.load(f)
    weekly = {}
    for k, v in raw.items():
        y, w = k.rsplit("-", 1)
        weekly[(int(y), int(w))] = v
    return weekly, start, end


def walkforward(cfg):
    """OUT-OF-SAMPLE validation — the honest test that separates a real edge
    from overfitting. Train: pick the best-robust params on the FIRST 70% of
    weeks. Test: run those params, untouched, on the LAST 30% the optimizer
    never saw. If the edge only exists in-sample, it isn't an edge.
    Writes data/walkforward.json for the learning loop."""
    import copy
    import statistics
    from collections import defaultdict

    weekly, start, end = _load_candidate_cache()
    weeks = sorted(weekly)
    cut = max(1, int(len(weeks) * 0.7))
    boundary_week = weeks[cut]
    boundary = dt.date.fromisocalendar(boundary_week[0], boundary_week[1], 1)
    train_w = {w: v for w, v in weekly.items() if w < boundary_week}
    test_w = {w: v for w, v in weekly.items() if w >= boundary_week}
    print("walk-forward: train {} weeks (to {}), test {} weeks".format(
        len(train_w), boundary, len(test_w)))

    tickers = sorted({c["ticker"] for v in weekly.values() for c in v})
    hist = download_history(tickers, start, end)
    spy = yf.download("SPY", start=start.isoformat(),
                      end=(end + dt.timedelta(days=1)).isoformat(),
                      interval="1d", progress=False, auto_adjust=True)
    all_days = list(spy.index.to_pydatetime())
    train_days = [d for d in all_days if d.date() < boundary]
    test_days = [d for d in all_days if d.date() >= boundary]

    def run(days, wk, stop, tp, buys, min_score):
        c = copy.deepcopy(cfg)
        c["selling"]["trailing_stop_pct"] = stop
        c["selling"]["take_profit_pct"] = tp
        c["buying"]["max_buys_per_week"] = buys
        w2 = {k: [x for x in v if x["score"] >= min_score] for k, v in wk.items()}
        cash, positions, trades, curve, final_open = simulate(c, w2, hist, days, start)
        open_val = sum((p["now"] or p["cost"]) * p["shares"] for p in final_open)
        dep = c["monthly_deposit_usd"] * len({d[:7] for d, _ in curve}) or 1
        return round(((cash + open_val) / dep - 1) * 100, 2), len(trades)

    # train: group combos, rank by median return across min_score variants
    groups = defaultdict(list)
    for stop in (8.0, 10.0, 12.0, 15.0):
        for tp in (15.0, 20.0, 25.0, 999.0):
            for buys in (1, 2, 3, 4):
                for ms in (4.5, 5.0, 5.5, 6.0):
                    ret, _ = run(train_days, train_w, stop, tp, buys, ms)
                    groups[(stop, tp, buys)].append((ms, ret))
    ranked = sorted(groups.items(),
                    key=lambda kv: statistics.median(r for _, r in kv[1]), reverse=True)

    results = []
    for (stop, tp, buys), variants in ranked[:5]:
        train_med = statistics.median(r for _, r in variants)
        best_ms = max(variants, key=lambda x: x[1])[0]
        test_ret, test_trades = run(test_days, test_w, stop, tp, buys, best_ms)
        results.append({"stop": stop, "tp": tp, "buys_wk": buys, "min_score": best_ms,
                        "train_median_pct": round(train_med, 2),
                        "test_pct": test_ret, "test_trades": test_trades})

    spy_c = spy["Close"].squeeze()
    spy_test = [float(x) for x in spy_c[spy_c.index >= str(boundary)]]
    spy_test_ret = round((spy_test[-1] / spy_test[0] - 1) * 100, 2) if len(spy_test) > 1 else None

    top = results[0]
    holds = top["test_pct"] > 0
    beats_spy = spy_test_ret is not None and top["test_pct"] > spy_test_ret
    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "train_period": "{} to {}".format(start, boundary),
        "test_period": "{} to {}".format(boundary, end),
        "top5_train_combos_tested_oos": results,
        "spy_test_return_pct": spy_test_ret,
        "verdict": {
            "edge_survives_out_of_sample": holds,
            "beats_spy_out_of_sample": bool(beats_spy),
            "read": ("PASS: params picked on train also made {}% on unseen data"
                     .format(top["test_pct"]) if holds else
                     "FAIL: train-best params lost {}% on unseen data — in-sample "
                     "results are overfit; do NOT trust the backtest headline"
                     .format(top["test_pct"])),
        },
    }
    with open(os.path.join(DATA_DIR, "walkforward.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out["verdict"], indent=2))
    print("top-5 train combos, tested out-of-sample:")
    for r in results:
        print("  stop {stop} tp {tp} buys {buys_wk} ms {min_score}: "
              "train {train_median_pct}% -> TEST {test_pct}% ({test_trades} trades)".format(**r))
    print("SPY over test window: {}%".format(spy_test_ret))
    print("saved: data/walkforward.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=4)
    ap.add_argument("--tune", action="store_true",
                    help="parameter sweep using cached candidates from a prior full run")
    ap.add_argument("--walkforward", action="store_true",
                    help="out-of-sample validation: train on first 70%% of weeks, test on last 30%%")
    args = ap.parse_args()

    cfg = botconfig.load()
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=args.months * 30)
    if args.walkforward:
        walkforward(cfg)
        return
    if args.tune:
        tune(cfg, start, end)
        return
    sess = sec_session(cfg)
    print("backtest {} -> {}".format(start, end), flush=True)

    cikmap = cik_to_ticker_map(sess)
    print("phase 1: collecting Form 4 events from daily indexes...", flush=True)
    events = collect_events(sess, cikmap, start, end)
    print("  {} issuer filings".format(len(events)), flush=True)

    tickers = sorted({e[1] for e in events})
    print("phase 2: downloading history for {} tickers...".format(len(tickers)), flush=True)
    hist = download_history(tickers, start, end)

    print("phase 3: price-filter + parse filings...", flush=True)
    u = cfg["universe"]
    weekly = {}
    checked = kept = 0
    by_week_ticker = {}
    pcache = load_purchase_cache()
    for date_iso, ticker, cik, path in events:
        if ticker not in hist:
            continue
        m = metrics_asof(hist[ticker], date_iso)
        if m is None:
            continue
        price, adv, ret5d, above_ma20, ext = m
        if not (u["price_min"] <= price <= u["price_max"] and adv >= u["min_avg_dollar_volume"]):
            continue
        checked += 1
        if path in pcache:
            parsed = tuple(pcache[path]) if pcache[path] else None
        else:
            parsed = parse_txt_form4(sess, path)
            pcache[path] = list(parsed) if parsed else None
            if checked % 200 == 0:
                save_purchase_cache(pcache)
        if not parsed:
            continue
        owner, usd = parsed
        if usd < cfg["signals"]["insider_min_purchase_usd"]:
            continue
        kept += 1
        week = dt.date.fromisoformat(date_iso).isocalendar()[:2]
        key = (week, ticker)
        agg = by_week_ticker.setdefault(key, {"total_usd": 0, "owners": set(),
                                              "mom": (ret5d > 0 and above_ma20),
                                              "ext": ext})
        agg["total_usd"] += usd
        agg["owners"].add(owner)
    print("  filings parsed: {}, qualifying purchases: {}".format(checked, kept), flush=True)

    w = cfg["signals"]
    for (week, ticker), agg in by_week_ticker.items():
        if agg["ext"] > cfg["confluence"]["max_extension_pct"]:
            continue  # too extended: crude price-action gate
        ins = {"total_usd": agg["total_usd"], "n_insiders": len(agg["owners"]),
               "filings": 0}
        score = insider_score(ins) * w["insider_weight"] + (0.5 if agg["mom"] else 0.0)
        if score < 2.5:  # core-signal threshold (no sector/fundamentals/news here)
            continue
        weekly.setdefault(week, []).append({"ticker": ticker, "score": round(score, 2)})
    print("  weeks with candidates: {}".format(len(weekly)), flush=True)
    save_purchase_cache(pcache)
    cand_cache = os.path.join(CACHE_DIR, "bt_candidates_{}_{}.json".format(start, end))
    with open(cand_cache, "w") as f:
        json.dump({"{}-{}".format(*k): v for k, v in weekly.items()}, f)

    spy = yf.download("SPY", start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(),
                      interval="1d", progress=False, auto_adjust=True)
    trading_days = list(spy.index.to_pydatetime())

    print("phase 4: simulating (week-by-week)...", flush=True)
    cash, positions, trades, curve, final_open = simulate(
        cfg, weekly, hist, trading_days, start, progress=True)

    open_val = sum((p["now"] or p["cost"]) * p["shares"] for p in final_open)
    deposited = cfg["monthly_deposit_usd"] * len({d[:7] for d, _ in curve})
    final_equity = cash + open_val
    wins = [t for t in trades if t["usd"] > 0]
    losses = [t for t in trades if t["usd"] <= 0]

    spy_close = spy["Close"].squeeze()
    spy_ret = float(spy_close.iloc[-1] / spy_close.iloc[0] - 1) * 100

    peak, maxdd = 0.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            maxdd = max(maxdd, (1 - eq / peak) * 100)

    report = {
        "period": "{} to {}".format(start, end),
        "deposited": deposited,
        "final_equity": round(final_equity, 2),
        "return_pct": round((final_equity / deposited - 1) * 100, 1),
        "closed_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
        "avg_win_pct": round(sum(t["pct"] for t in wins) / len(wins), 1) if wins else None,
        "avg_loss_pct": round(sum(t["pct"] for t in losses) / len(losses), 1) if losses else None,
        "max_drawdown_pct": round(maxdd, 1),
        "spy_buy_hold_return_pct": round(spy_ret, 1),
        "open_at_end": final_open,
        "trades": trades,
        "caveats": [
            "fills at daily close, zero spread/slippage — optimistic",
            "no news/VWAP/spread/IV/research signals — core engine only",
            "current CIK->ticker map: delisted names excluded (survivorship bias)",
        ],
    }
    with open(os.path.join(DATA_DIR, "backtest_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    with open(os.path.join(DATA_DIR, "backtest_equity.csv"), "w") as f:
        f.write("date,equity\n")
        f.writelines("{},{}\n".format(d, e) for d, e in curve)

    print(json.dumps({k: v for k, v in report.items() if k not in ("trades", "open_at_end")},
                     indent=2))
    print("\ntrades:")
    for t in trades:
        print("  {in} -> {out}  {ticker} x{shares}  {pct:+.1f}%  (${usd:+.2f})  [{exit}]".format(**t))
    print("\nfull report: data/backtest_report.json")


if __name__ == "__main__":
    main()
