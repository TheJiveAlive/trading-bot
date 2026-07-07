"""Self-contained HTML dashboard, regenerated after every scan.

Writes dashboard.html at the project root (open in any browser; auto-refreshes
every 5 minutes). Dark terminal aesthetic; no external assets, so it works
from file:// or any static server.
"""
import datetime as dt
import json
import os
import re

from bot import config, ledger, market, risk
from bot.config import ROOT

CSS = """
:root { --bg:#0A0F1A; --panel:#121B2E; --line:#1E2B47; --ink:#E8EDF7;
  --mut:#8494B0; --amber:#E8B84B; --gain:#35C77C; --loss:#F0564D; }
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--ink); padding:28px 16px 60px;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:1080px; margin:0 auto; display:flex; flex-direction:column; gap:14px; }
.mono { font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums; }
.strip { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.strip h1 { font-size:17px; font-weight:800; letter-spacing:.4px; }
.strip .zap { color:var(--amber); }
.pill { border:1px solid var(--line); border-radius:3px; padding:3px 10px;
  font-size:10.5px; font-weight:700; letter-spacing:1.6px; text-transform:uppercase; }
.pill.paper { color:var(--amber); border-color:#3d3319; background:#1c1810; }
.pill.wait { color:var(--mut); }
.pill.regime-risk_on { color:var(--gain); } .pill.regime-risk_off { color:var(--loss); }
.pill.regime-neutral { color:var(--mut); }
.gen { margin-left:auto; color:var(--mut); font-size:11.5px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
.kpi { background:var(--panel); border:1px solid var(--line); border-radius:4px;
  padding:12px 14px; }
.kpi .l { color:var(--mut); font-size:10px; font-weight:700; letter-spacing:1.6px;
  text-transform:uppercase; }
.kpi .v { font-size:21px; font-weight:700; margin-top:5px; }
.grid2 { display:grid; grid-template-columns:3fr 2fr; gap:14px; }
@media (max-width:800px){ .grid2 { grid-template-columns:1fr; } }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:4px;
  padding:14px 16px; overflow-x:auto; }
.panel h2 { color:var(--mut); font-size:10.5px; font-weight:700; letter-spacing:1.8px;
  text-transform:uppercase; margin-bottom:10px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th { text-align:left; color:var(--mut); font-size:10px; letter-spacing:1.4px;
  text-transform:uppercase; padding:6px 8px; border-bottom:1px solid var(--line); }
td { padding:7px 8px; border-bottom:1px solid #16213A; vertical-align:top; }
tr:last-child td { border-bottom:none; }
.r { text-align:right; } th.r { text-align:right; }
.gain { color:var(--gain); } .loss { color:var(--loss); } .mut { color:var(--mut); }
.bar { height:5px; background:#1A2540; border-radius:2px; min-width:70px; }
.bar i { display:block; height:5px; background:var(--amber); border-radius:2px; }
.chips { display:flex; gap:6px; flex-wrap:wrap; }
.chip { border:1px solid var(--line); border-radius:3px; padding:2px 8px;
  font-size:11px; color:var(--mut); }
.chip.pos { color:var(--gain); border-color:#1c3a2c; }
.chip.neg { color:var(--loss); border-color:#4022214; }
.note { font-size:12px; color:var(--mut); line-height:1.55; margin-top:8px; }
.klabel { color:var(--mut); font-size:11px; margin-top:9px; letter-spacing:.4px; }
.foot { color:var(--mut); font-size:11px; text-align:center; margin-top:6px; line-height:1.7; }
"""


def _fetch_state():
    cfg = config.load()
    con = ledger.connect()
    cash = ledger.cash(con)
    positions = []
    for p in ledger.open_positions(con):
        price = market.last_price(p["ticker"])
        positions.append({**p, "now": price,
                          "pl_pct": (price / p["avg_cost"] - 1) * 100 if price else None,
                          "pl_usd": (price - p["avg_cost"]) * p["shares"] if price else None})
    equity = cash + sum((p["now"] or p["avg_cost"]) * p["shares"] for p in positions)
    ledger.record_equity(con, equity, cash)
    con.commit()

    deposited = 0.0
    for (detail,) in con.execute("SELECT detail FROM decisions WHERE kind='deposit'"):
        m = re.search(r"\$([\d.]+)", detail)
        if m:
            deposited += float(m.group(1))
    curve = con.execute("SELECT ts, equity FROM equity_history ORDER BY id").fetchall()
    trades = con.execute("SELECT ts,side,ticker,shares,price,value,mode,reason "
                         "FROM trades ORDER BY id DESC LIMIT 12").fetchall()
    decisions = con.execute("SELECT ts,kind,detail FROM decisions "
                            "ORDER BY id DESC LIMIT 14").fetchall()
    cand_rows = con.execute("SELECT ticker,score,detail FROM scan_candidates "
                            "ORDER BY id DESC LIMIT 24").fetchall()
    con.close()
    seen, candidates = set(), []
    for t, s, d in cand_rows:
        if t not in seen:
            seen.add(t)
            candidates.append((t, s, json.loads(d)))
    candidates = sorted(candidates[:8], key=lambda c: c[1], reverse=True)
    return cfg, cash, positions, equity, deposited, curve, trades, decisions, candidates


def _svg_curve(curve, deposited):
    if not curve:
        return '<div class="mut">no equity history yet</div>'
    pts = [e for _, e in curve]
    if len(pts) == 1:
        pts = pts * 2
    w, h, pad = 560, 150, 8
    lo, hi = min(pts + [deposited]), max(pts + [deposited])
    if hi - lo < 1:
        lo, hi = lo - 1, hi + 1
    def x(i): return pad + i * (w - 2 * pad) / (len(pts) - 1)
    def y(v): return h - pad - (v - lo) * (h - 2 * pad) / (hi - lo)
    line = " ".join("{:.1f},{:.1f}".format(x(i), y(v)) for i, v in enumerate(pts))
    dep_y = y(deposited)
    color = "#35C77C" if pts[-1] >= deposited else "#F0564D"
    return ('<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="equity curve">'
            '<line x1="{p}" y1="{dy:.1f}" x2="{w2}" y2="{dy:.1f}" stroke="#8494B0" '
            'stroke-width="1" stroke-dasharray="4 4" opacity="0.5"/>'
            '<polyline points="{line}" fill="none" stroke="{c}" stroke-width="2"/>'
            '<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{c}"/>'
            '<text x="{p}" y="{dty:.1f}" fill="#8494B0" font-size="9" '
            'font-family="Menlo,monospace">deposited ${d:,.0f}</text></svg>'
            '<div class="klabel mono">${first:,.2f} &rarr; ${last:,.2f} over {n} snapshots</div>'
            ).format(w=w, h=h, p=pad, w2=w - pad, dy=dep_y, line=line, c=color,
                     cx=x(len(pts) - 1), cy=y(pts[-1]),
                     dty=max(dep_y - 5, 10), d=deposited,
                     first=curve[0][1], last=curve[-1][1], n=len(curve))


def _positions_rows(positions):
    if not positions:
        return '<tr><td colspan="6" class="mut">flat — no open positions</td></tr>'
    out = []
    for p in positions:
        cls = "mut" if p["pl_pct"] is None else ("gain" if p["pl_pct"] >= 0 else "loss")
        out.append(
            '<tr><td class="mono"><b>{t}</b></td><td class="mono r">{sh}</td>'
            '<td class="mono r">${c:.2f}</td><td class="mono r">{n}</td>'
            '<td class="mono r {cls}">{usd}</td><td class="mono r {cls}">{pct}</td></tr>'.format(
                t=p["ticker"], sh=p["shares"], c=p["avg_cost"],
                n="${:.2f}".format(p["now"]) if p["now"] else "—", cls=cls,
                usd="{}${:.2f}".format("+" if p["pl_usd"] >= 0 else "−", abs(p["pl_usd"]))
                    if p["pl_usd"] is not None else "—",
                pct="{:+.1f}%".format(p["pl_pct"]) if p["pl_pct"] is not None else "—"))
    return "".join(out)


def _candidate_rows(candidates):
    if not candidates:
        return '<tr><td colspan="4" class="mut">no candidates in the last scan</td></tr>'
    top = max(c[1] for c in candidates) or 1
    out = []
    for t, s, d in candidates:
        parts = ", ".join("{} {}".format(k, v) for k, v in (d.get("parts") or {}).items())
        out.append(
            '<tr><td class="mono"><b>{t}</b><div class="mut" style="font-size:10.5px">{name}</div></td>'
            '<td class="mono r">{price}</td>'
            '<td style="width:90px"><div class="bar"><i style="width:{w:.0f}%"></i></div></td>'
            '<td class="mono r">{s}</td></tr>'
            '<tr><td colspan="4" class="mut" style="font-size:10.5px;padding-top:0">{parts}</td></tr>'.format(
                t=t, name=(d.get("name") or "")[:34],
                price="${:.2f}".format(d["price"]) if d.get("price") else "—",
                w=100 * s / top, s=s, parts=parts))
    return "".join(out)


def _trade_rows(trades):
    if not trades:
        return '<tr><td colspan="6" class="mut">no trades yet</td></tr>'
    out = []
    for ts, side, t, sh, price, value, mode, reason in trades:
        cls = "gain" if side == "buy" else "loss"
        out.append(
            '<tr><td class="mono mut">{d}</td><td class="mono {cls}"><b>{side}</b></td>'
            '<td class="mono"><b>{t}</b></td><td class="mono r">{sh}</td>'
            '<td class="mono r">${p:.2f}</td><td class="mono r">${v:.2f}</td></tr>'.format(
                d=ts[5:16].replace("T", " "), cls=cls, side=side.upper(), t=t,
                sh=sh, p=price, v=value))
    return "".join(out)


def _decision_rows(decisions):
    out = []
    for ts, kind, detail in decisions:
        out.append('<tr><td class="mono mut" style="white-space:nowrap">{d}</td>'
                   '<td><span class="chip">{k}</span></td>'
                   '<td class="mut" style="font-size:11.5px">{txt}</td></tr>'.format(
                       d=ts[5:16].replace("T", " "), k=kind, txt=detail[:180]))
    return "".join(out) or '<tr><td class="mut">nothing logged yet</td></tr>'


def _research_panel(research):
    if not research or research.get("_stale"):
        return '<div class="mut">no fresh research — bot running neutral</div>'
    regime = risk.regime(research)
    bias = research.get("sector_bias", {})
    chips = "".join('<span class="chip {c}">{s} {v:+.1f}</span>'.format(
        c="pos" if v > 0 else "neg", s=s, v=v) for s, v in bias.items())
    watch = ", ".join(risk.watchlist_tickers(research)) or "—"
    avoid = ", ".join(sorted(risk.avoid_tickers(research))) or "—"
    return ('<div class="chips"><span class="pill regime-{r}">{rt}</span></div>'
            '<div class="note">{reason}</div>'
            '<div class="klabel">SECTOR BIAS</div><div class="chips">{chips}</div>'
            '<div class="klabel">WATCHLIST</div><div class="note mono">{w}</div>'
            '<div class="klabel">AVOID</div><div class="note mono loss">{a}</div>'
            '<div class="klabel">NOTES</div><div class="note">{n}</div>').format(
        r=regime, rt=regime.replace("_", " "), reason=research.get("regime_reason", ""),
        chips=chips or '<span class="mut">none</span>', w=watch, a=avoid,
        n=research.get("notes", ""))


def generate():
    cfg, cash, positions, equity, deposited, curve, trades, decisions, candidates = _fetch_state()
    research = risk.load_research()
    unreal = sum(p["pl_usd"] or 0 for p in positions)
    net = equity - deposited if deposited else 0.0
    net_cls = "gain" if net >= 0 else "loss"
    unreal_cls = "gain" if unreal >= 0 else "loss"
    gen_time = dt.datetime.now().strftime("%a %d %b %Y, %H:%M")

    body = """
<div class="wrap">
  <div class="strip">
    <h1><span class="zap">&#9889;</span> RobinHood Bot</h1>
    <span class="pill paper">{mode} trading</span>
    <span class="pill wait">connector: awaiting auth</span>
    <span class="gen mono">generated {gen} &middot; auto-refreshes every 5 min</span>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="l">Total equity</div><div class="v mono">${equity:,.2f}</div></div>
    <div class="kpi"><div class="l">Cash</div><div class="v mono">${cash:,.2f}</div></div>
    <div class="kpi"><div class="l">Deposited</div><div class="v mono">${dep:,.2f}</div></div>
    <div class="kpi"><div class="l">Net P/L</div><div class="v mono {net_cls}">{net_sign}${net:,.2f}</div></div>
    <div class="kpi"><div class="l">Unrealized</div><div class="v mono {unreal_cls}">{ur_sign}${unreal:,.2f}</div></div>
  </div>

  <div class="grid2">
    <div class="panel"><h2>Equity curve</h2>{curve}</div>
    <div class="panel"><h2>Research &middot; {rdate}</h2>{research}</div>
  </div>

  <div class="panel"><h2>Open positions</h2>
    <table><tr><th>Ticker</th><th class="r">Shares</th><th class="r">Avg cost</th>
    <th class="r">Now</th><th class="r">P/L $</th><th class="r">P/L %</th></tr>{positions}</table>
  </div>

  <div class="grid2">
    <div class="panel"><h2>Latest scan candidates</h2>
      <table><tr><th>Ticker</th><th class="r">Price</th><th>Score</th><th class="r"></th></tr>{cands}</table>
    </div>
    <div class="panel"><h2>Recent trades</h2>
      <table><tr><th>When</th><th>Side</th><th>Ticker</th><th class="r">Qty</th>
      <th class="r">Price</th><th class="r">Value</th></tr>{trades}</table>
    </div>
  </div>

  <div class="panel"><h2>Decision log</h2><table>{decisions}</table></div>

  <div class="foot">Paper trading with live market data &middot; scans weekdays
  14:30 / 16:30 / 18:30 / 20:30 &middot; research daily 13:37 &middot; review Sundays<br/>
  Flip to live in config.json once the Robinhood connector is authorized.</div>
</div>""".format(
        mode=cfg["mode"], gen=gen_time, equity=equity, cash=cash, dep=deposited,
        net_cls=net_cls, net_sign="+" if net >= 0 else "−", net=abs(net),
        unreal_cls=unreal_cls, ur_sign="+" if unreal >= 0 else "−", unreal=abs(unreal),
        curve=_svg_curve(curve, deposited), rdate=research.get("date", "—"),
        research=_research_panel(research), positions=_positions_rows(positions),
        cands=_candidate_rows(candidates), trades=_trade_rows(trades),
        decisions=_decision_rows(decisions))

    standalone = ('<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
                  '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
                  '<meta http-equiv="refresh" content="300"/>'
                  '<title>RobinHood Bot</title><style>{}</style></head>'
                  '<body>{}</body></html>').format(CSS, body)
    out = os.path.join(ROOT, "dashboard.html")
    with open(out, "w") as f:
        f.write(standalone)
    publish_dir = os.path.join(ROOT, "publish")
    if os.path.isdir(publish_dir):
        with open(os.path.join(publish_dir, "index.html"), "w") as f:
            f.write(standalone)
    return out, "<title>RobinHood Bot — Paper Dashboard</title><style>{}</style>{}".format(CSS, body)


if __name__ == "__main__":
    path, _ = generate()
    print("wrote", path)
