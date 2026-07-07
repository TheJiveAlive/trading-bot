"""Revenue/earnings health from yfinance info for candidate tickers."""


def fundamentals_score(info):
    """0..2. Rewards revenue growth and improving earnings; penalises heavy
    dilution risk signals (negative margins with no growth)."""
    score = 0.0
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")
    margins = info.get("profitMargins")

    if rev_growth is not None:
        if rev_growth > 0.30:
            score += 1.5
        elif rev_growth > 0.10:
            score += 1.0
        elif rev_growth > 0:
            score += 0.5
    if earn_growth is not None and earn_growth > 0:
        score += 0.5
    if margins is not None and margins < -0.5 and (rev_growth or 0) <= 0:
        score -= 1.0
    return max(0.0, min(score, 2.0))
