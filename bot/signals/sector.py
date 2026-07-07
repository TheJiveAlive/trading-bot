"""Sector momentum via SPDR sector ETF relative strength (1M and 3M returns)."""
import warnings

warnings.filterwarnings("ignore")

import yfinance as yf

from bot.market import SECTOR_ETFS


def sector_momentum_ranks():
    """{sector_name: score 0..1}, 1 = strongest sector."""
    etfs = list(SECTOR_ETFS.values())
    df = yf.download(etfs, period="4mo", interval="1d", progress=False,
                     group_by="ticker", auto_adjust=True)
    perf = {}
    for name, etf in SECTOR_ETFS.items():
        try:
            closes = (df[etf]["Close"] if len(etfs) > 1 else df["Close"]).dropna()
            if len(closes) < 64:
                continue
            r1m = closes.iloc[-1] / closes.iloc[-21] - 1
            r3m = closes.iloc[-1] / closes.iloc[-63] - 1
            perf[name] = 0.6 * r1m + 0.4 * r3m
        except Exception:
            continue
    if not perf:
        return {}
    ranked = sorted(perf, key=perf.get)
    n = len(ranked)
    return {name: (i / (n - 1) if n > 1 else 1.0) for i, name in enumerate(ranked)}


def sector_score(sector_name, ranks):
    """0..1 for the stock's sector; 0.5 when sector unknown."""
    if not sector_name or sector_name not in ranks:
        return 0.5
    return ranks[sector_name]
