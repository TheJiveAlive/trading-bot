"""Forward-looking catalyst signals: upcoming earnings and volume breakouts.

These look for reasons to OPEN a trade where gains are plausibly ahead —
complementing the insider/sector core with momentum-into-event setups.
"""
import warnings

warnings.filterwarnings("ignore")

import yfinance as yf

from bot.signals.technicals import days_to_earnings


def earnings_catalyst_score(cfg, ticker, ret5d_pct, news_sc):
    """0..1.5. Positive only when earnings sit in the catalyst window AND the
    stock is already moving up with non-negative news — i.e. a pre-earnings
    run-up setup, exited before the actual print (see manage_exits)."""
    ec = cfg.get("earnings", {})
    lo, hi = ec.get("catalyst_window_min", 3), ec.get("catalyst_window_max", 15)
    d = days_to_earnings(ticker)
    if d is None or not (lo <= d <= hi):
        return 0.0, None
    if ret5d_pct is None or ret5d_pct <= 0 or news_sc < 0:
        return 0.0, "earnings in {}d but momentum/news not supportive".format(d)
    score = 0.75
    if ret5d_pct > 5:
        score += 0.5
    if news_sc > 0.5:
        score += 0.25
    return min(score, 1.5), "earnings in {}d with +{:.1f}% 5d momentum".format(d, ret5d_pct)


def breakout_score(ticker):
    """0..1.5. Rewards a fresh push toward 52-week highs on expanding volume —
    a classic momentum-breakout tell that news/indicators are aligning."""
    try:
        h = yf.Ticker(ticker).history(period="1y")
        if h is None or len(h) < 60:
            return 0.0, None
        closes = h["Close"].dropna()
        vols = h["Volume"].dropna()
        last = float(closes.iloc[-1])
        hi_52 = float(closes.max())
        near_high = last >= hi_52 * 0.95
        recent_vol = float(vols.iloc[-3:].mean())
        base_vol = float(vols.iloc[-30:-3].mean()) or 1
        vol_surge = recent_vol / base_vol
        above_50dma = last > float(closes.iloc[-50:].mean())
        score = 0.0
        note = []
        if near_high:
            score += 0.75
            note.append("within 5% of 52w high")
        if vol_surge > 1.5 and above_50dma:
            score += 0.75
            note.append("vol {:.1f}x on uptrend".format(vol_surge))
        return min(score, 1.5), (", ".join(note) if note else None)
    except Exception:
        return 0.0, None


def earnings_exit_due(cfg, ticker):
    """True if earnings are within exit_days_before — sell to avoid the print."""
    d = days_to_earnings(ticker)
    if d is None:
        return False
    return 0 <= d <= cfg.get("earnings", {}).get("exit_days_before", 1)
