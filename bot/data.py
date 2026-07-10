"""Unified price-data aggregator — the 'hybrid of all sources'.

Tries sources in priority order (fastest/best first) and falls back, so no
single provider being slow, throttled, or thin-on-coverage stops the bot. Each
source is a small function; adding a paid one later (Tiingo/EODHD/Polygon) is a
one-line insert into SOURCES — that's the "when I ask again next week" hook.

NOTE: Trading 212's API is NOT a data source — it only exposes your account,
instruments metadata, and order history, no market OHLC/quotes. So it's the
execution venue, never a price feed.
"""

# ---- individual sources (each returns {ticker: price} for the ones it knows) ----

def _alpaca(tickers):
    try:
        from bot import alpaca
        if alpaca.configured():
            return alpaca.latest_prices(tickers)   # real-time IEX, fast, thin coverage
    except Exception:
        pass
    return {}


def _yahoo(tickers):
    from bot import market
    out = {}
    for t in tickers:
        try:
            import yfinance as yf
            h = yf.Ticker(t).history(period="5d")
            if h is not None and not h.empty:
                out[t] = float(h["Close"].dropna().iloc[-1])
        except Exception:
            continue
    return out


# Priority chain: fast/real-time first, complete/free last. Insert a paid
# bulk source (e.g. _tiingo) ABOVE _yahoo next week to speed everything up.
SOURCES = [("alpaca", _alpaca), ("yahoo", _yahoo)]


def get_prices(tickers):
    """{ticker: price} aggregated across sources; each ticker filled by the
    highest-priority source that has it. Returns which source served what."""
    remaining = list(dict.fromkeys(tickers))
    prices, served = {}, {}
    for name, fn in SOURCES:
        if not remaining:
            break
        got = fn(remaining) or {}
        for t, p in got.items():
            if p and t not in prices:
                prices[t] = p
                served[t] = name
        remaining = [t for t in remaining if t not in prices]
    return prices, served


def get_last(ticker):
    """Single-ticker convenience — same fallback chain."""
    prices, _ = get_prices([ticker])
    return prices.get(ticker)
