"""HTML email templates: branded trade alerts with charts and portfolio table.

Email-client CSS is primitive (Gmail strips <style> blocks and SVG), so
everything is inline styles on tables, and charts are PNGs embedded by
Content-ID. A plain-text fallback always accompanies the HTML.
"""
import datetime as dt
import io
import warnings

warnings.filterwarnings("ignore")

GREEN = "#16a34a"
RED = "#dc2626"
INK = "#0f172a"
MUTED = "#64748b"
BG = "#f1f5f9"
CARD = "#ffffff"
BORDER = "#e2e8f0"

FONT = ("font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "Helvetica,Arial,sans-serif;")


def price_chart_png(ticker, entry_price=None, entry_date=None,
                    exit_price=None, exit_date=None, period="3mo"):
    """PNG bytes: price line with entry/exit markers. None on any failure."""
    try:
        import yfinance as yf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        h = yf.Ticker(ticker).history(period=period)
        if h is None or len(h) < 5:
            return None
        closes = h["Close"].dropna()

        fig, ax = plt.subplots(figsize=(6.0, 2.4), dpi=160)
        fig.patch.set_facecolor("white")
        ax.plot(closes.index, closes.values, color="#2563eb", linewidth=1.6)
        ax.fill_between(closes.index, closes.values, closes.values.min(),
                        color="#2563eb", alpha=0.08)

        def _mark(date, price, color, label):
            x = None
            if date is not None:
                try:
                    ts = closes.index[closes.index.strftime("%Y-%m-%d") >= date]
                    x = ts[0] if len(ts) else closes.index[-1]
                except Exception:
                    x = closes.index[-1]
            else:
                x = closes.index[-1]
            ax.scatter([x], [price], color=color, zorder=5, s=42)
            ax.annotate(label, (x, price), textcoords="offset points",
                        xytext=(6, 8), fontsize=8, color=color, fontweight="bold")

        if entry_price:
            _mark(entry_date, entry_price, GREEN, "BUY ${:.2f}".format(entry_price))
        if exit_price:
            _mark(exit_date, exit_price, RED, "SELL ${:.2f}".format(exit_price))

        ax.set_title("{} — 3 months".format(ticker), fontsize=10,
                     color=INK, loc="left", fontweight="bold")
        ax.tick_params(labelsize=7, colors=MUTED)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color(BORDER)
        ax.grid(axis="y", color=BORDER, linewidth=0.5, alpha=0.6)
        fig.tight_layout(pad=0.8)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor="white")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def _pnl_pill(pnl_usd, pnl_pct):
    color = GREEN if pnl_usd >= 0 else RED
    sign = "+" if pnl_usd >= 0 else "−"
    return ('<span style="background:{c};color:#fff;border-radius:14px;'
            'padding:4px 14px;font-size:15px;font-weight:700;{f}">'
            '{s}${v:,.2f} ({s}{p:.1f}%)</span>').format(
        c=color, f=FONT, s=sign, v=abs(pnl_usd), p=abs(pnl_pct))


def _portfolio_rows(positions):
    if not positions:
        return ('<tr><td colspan="5" style="padding:10px;color:{m};{f}'
                'font-size:13px;">no open positions</td></tr>').format(m=MUTED, f=FONT)
    rows = []
    for p in positions:
        pct = p.get("unrealized_pct")
        color = MUTED if pct is None else (GREEN if pct >= 0 else RED)
        pct_txt = "—" if pct is None else "{:+.1f}%".format(pct)
        now = p.get("current_price")
        rows.append(
            '<tr>'
            '<td style="padding:8px 10px;{f}font-size:13px;font-weight:600;color:{i};">{t}</td>'
            '<td style="padding:8px 10px;{f}font-size:13px;color:{m};" align="right">{sh}</td>'
            '<td style="padding:8px 10px;{f}font-size:13px;color:{m};" align="right">${c:.2f}</td>'
            '<td style="padding:8px 10px;{f}font-size:13px;color:{m};" align="right">{n}</td>'
            '<td style="padding:8px 10px;{f}font-size:13px;font-weight:700;color:{pc};" align="right">{p}</td>'
            '</tr>'.format(
                f=FONT, i=INK, m=MUTED, pc=color, t=p["ticker"], sh=p["shares"],
                c=p["avg_cost"], n="${:.2f}".format(now) if now else "—", p=pct_txt))
    return "".join(rows)


def trade_email(side, ticker, shares, price, mode, reasons, positions, cash,
                pnl_usd=None, pnl_pct=None, note=None, has_chart=True):
    """(subject, html, text). reasons: list of short strings. has_chart=False
    omits the chart row entirely (no broken-image box when the PNG can't be
    generated, e.g. slim cloud runners)."""
    side_u = side.upper()
    side_color = GREEN if side_u == "BUY" else RED
    total = shares * price
    today = dt.date.today().strftime("%A %d %B %Y")

    subject = "{} {} — {} shares @ ${:.2f}".format(
        "🟢" if side_u == "BUY" else "🔴", "{} {}".format(side_u, ticker),
        shares, price)
    if pnl_usd is not None:
        subject += "  ·  P/L {}${:.2f} ({:+.1f}%)".format(
            "+" if pnl_usd >= 0 else "−", abs(pnl_usd), pnl_pct)

    equity = cash + sum((p.get("current_price") or p["avg_cost"]) * p["shares"]
                        for p in positions)

    pnl_html = ""
    if pnl_usd is not None:
        pnl_html = ('<tr><td align="center" style="padding:2px 0 14px;">{}</td></tr>'
                    .format(_pnl_pill(pnl_usd, pnl_pct)))

    reasons_html = "".join(
        '<tr><td style="padding:3px 0;{f}font-size:13px;color:{i};">'
        '<span style="color:{a};font-weight:700;">&#8250;</span>&nbsp; {r}</td></tr>'.format(
            f=FONT, i=INK, a=side_color, r=r) for r in reasons)

    note_html = ""
    if note:
        note_html = ('<tr><td style="padding:10px 24px 0;"><table width="100%" '
                     'cellpadding="0" cellspacing="0"><tr><td style="background:#fef3c7;'
                     'border:1px solid #fde68a;border-radius:8px;padding:10px 12px;'
                     '{f}font-size:12px;color:#92400e;">{n}</td></tr></table></td></tr>'
                     ).format(f=FONT, n=note)

    chart_html = ""
    if has_chart:
        chart_html = ('<tr><td style="background:{card};padding:0 24px;" align="center">'
                      '<img src="cid:chart" width="552" style="max-width:100%;'
                      'border:1px solid {border};border-radius:8px;" '
                      'alt="{t} price chart"/></td></tr>').format(
            card=CARD, border=BORDER, t=ticker)

    html = """
<table width="100%" cellpadding="0" cellspacing="0" style="background:{bg};padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <tr><td style="background:{ink};border-radius:12px 12px 0 0;padding:16px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="{f}font-size:16px;font-weight:800;color:#fff;">&#9889; RobinHood Bot</td>
      <td align="right"><span style="background:{mode_bg};color:#fff;border-radius:10px;
        padding:3px 10px;{f}font-size:11px;font-weight:700;text-transform:uppercase;
        letter-spacing:1px;">{mode}</span></td>
    </tr></table>
  </td></tr>

  <tr><td style="background:{card};padding:22px 24px 6px;" align="center">
    <div style="{f}font-size:12px;color:{muted};letter-spacing:2px;
      text-transform:uppercase;padding-bottom:4px;">{today}</div>
    <div style="{f}font-size:32px;font-weight:800;color:{side_color};
      padding-bottom:2px;">{side} {ticker}</div>
    <div style="{f}font-size:15px;color:{ink};padding-bottom:12px;">
      {shares} shares @ ${price:.2f} &nbsp;&middot;&nbsp; ${total:,.2f}</div>
  </td></tr>
  <tr><td style="background:{card};" align="center"><table cellpadding="0"
    cellspacing="0">{pnl_html}</table></td></tr>

  {chart_html}

  {note_html}

  <tr><td style="background:{card};padding:16px 24px 4px;">
    <div style="{f}font-size:11px;font-weight:700;color:{muted};letter-spacing:1.5px;
      text-transform:uppercase;padding-bottom:6px;">Why the bot traded</div>
    <table cellpadding="0" cellspacing="0" width="100%">{reasons_html}</table>
  </td></tr>

  <tr><td style="background:{card};padding:16px 24px 4px;">
    <div style="{f}font-size:11px;font-weight:700;color:{muted};letter-spacing:1.5px;
      text-transform:uppercase;padding-bottom:6px;">Portfolio</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {border};
      border-radius:8px;">
      <tr style="background:{bg};">
        <td style="padding:8px 10px;{f}font-size:11px;font-weight:700;color:{muted};">TICKER</td>
        <td style="padding:8px 10px;{f}font-size:11px;font-weight:700;color:{muted};" align="right">SHARES</td>
        <td style="padding:8px 10px;{f}font-size:11px;font-weight:700;color:{muted};" align="right">AVG COST</td>
        <td style="padding:8px 10px;{f}font-size:11px;font-weight:700;color:{muted};" align="right">NOW</td>
        <td style="padding:8px 10px;{f}font-size:11px;font-weight:700;color:{muted};" align="right">P/L</td>
      </tr>
      {portfolio_rows}
    </table>
  </td></tr>

  <tr><td style="background:{card};padding:14px 24px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="{f}font-size:13px;color:{muted};">Cash <b style="color:{ink};">${cash:,.2f}</b></td>
      <td align="right" style="{f}font-size:13px;color:{muted};">Total equity
        <b style="color:{ink};">${equity:,.2f}</b></td>
    </tr></table>
  </td></tr>

  <tr><td style="background:{ink};border-radius:0 0 12px 12px;padding:12px 24px;"
    align="center">
    <div style="{f}font-size:10px;color:#94a3b8;">Automated strategy — small-cap
    insider &amp; momentum signals. Not financial advice. {mode_note}</div>
  </td></tr>

</table>
</td></tr></table>""".format(
        bg=BG, card=CARD, ink=INK, muted=MUTED, border=BORDER, f=FONT,
        side=side_u, side_color=side_color, ticker=ticker, shares=shares,
        price=price, total=total, today=today,
        mode=mode, mode_bg=GREEN if mode == "live" else "#64748b",
        pnl_html=pnl_html, reasons_html=reasons_html, note_html=note_html,
        chart_html=chart_html,
        portfolio_rows=_portfolio_rows(positions), cash=cash, equity=equity,
        mode_note="Simulated paper fill." if mode == "paper"
                  else "Live order — see pending_orders.json until confirmed.")

    text_lines = ["{} {} x{} @ ${:.2f} (${:,.2f})".format(side_u, ticker, shares, price, total)]
    if pnl_usd is not None:
        text_lines.append("P/L: {}${:.2f} ({:+.1f}%)".format(
            "+" if pnl_usd >= 0 else "-", abs(pnl_usd), pnl_pct))
    text_lines += ["why: " + "; ".join(reasons), "cash: ${:,.2f}".format(cash),
                   "equity: ${:,.2f}".format(equity)]
    return subject, html, "\n".join(text_lines)
