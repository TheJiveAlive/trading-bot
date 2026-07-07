"""Keyless quantitative market regime: VIX, SPY trend, credit appetite.

Complements the daily Claude research regime. The two are blended
conservatively in scan.py: whichever says to take LESS risk wins.
"""
import warnings

warnings.filterwarnings("ignore")

import yfinance as yf

RANK = {"risk_off": 0, "neutral": 1, "risk_on": 2}


def quant_regime():
    """('risk_on'|'neutral'|'risk_off', detail) or (None, {}) on data failure."""
    try:
        df = yf.download(["^VIX", "SPY", "HYG", "LQD"], period="1y",
                         interval="1d", progress=False, group_by="ticker",
                         auto_adjust=True)
        vix = float(df["^VIX"]["Close"].dropna().iloc[-1])
        spy = df["SPY"]["Close"].dropna()
        spy_above_200dma = float(spy.iloc[-1]) > float(spy.iloc[-200:].mean())
        hyg = df["HYG"]["Close"].dropna()
        lqd = df["LQD"]["Close"].dropna()
        ratio = (hyg / lqd).dropna()
        credit_appetite_rising = float(ratio.iloc[-1]) > float(ratio.iloc[-60])

        score = 0
        score += 1 if vix < 18 else (-1 if vix > 26 else 0)
        score += 1 if spy_above_200dma else -1
        score += 1 if credit_appetite_rising else -1

        regime = "risk_on" if score >= 2 else ("risk_off" if score <= -1 else "neutral")
        return regime, {"vix": round(vix, 1), "spy_above_200dma": spy_above_200dma,
                        "credit_appetite_rising": credit_appetite_rising,
                        "score": score}
    except Exception:
        return None, {}


def blend_conservative(research_regime, quant):
    """The more cautious of the two regimes wins."""
    if quant is None:
        return research_regime
    return quant if RANK[quant] < RANK.get(research_regime, 1) else research_regime
