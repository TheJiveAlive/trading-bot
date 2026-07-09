"""End-to-end health check: exercises every subsystem and emails a report.

  python3 -m bot.healthcheck

Each check returns (ok, detail). Nothing here places trades — it only reads
live data and verifies each moving part is reachable and sane.
"""
import datetime as dt
import traceback

from bot import config, ledger, market, risk, notify


def _try(fn):
    try:
        return fn()
    except Exception as e:
        return (False, "error: {}".format(e).replace("\n", " ")[:200])


def check_config():
    cfg = config.load()
    need = ["mode", "buying", "selling", "confluence", "risk", "learning", "signals"]
    missing = [k for k in need if k not in cfg]
    return (not missing, "mode={}, all sections present".format(cfg["mode"])
            if not missing else "MISSING sections: {}".format(missing))


def check_ledger():
    con = ledger.connect()
    cash = ledger.cash(con)
    n = len(ledger.open_positions(con))
    trades = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    con.close()
    return (True, "cash ${:,.2f}, {} open positions, {} trades logged".format(cash, n, trades))


def check_market_data():
    px = market.last_price("AAPL")
    return (px is not None and px > 0, "AAPL last price ${:.2f}".format(px or 0))


def check_universe_filter():
    cfg = config.load()
    filt, snap = market.make_universe_filter(cfg)
    elig = filt(["SOFI", "F", "PLUG", "AAPL"])
    return (len(snap) > 0, "{} priced, {} passed ${}-${} liquidity filter".format(
        len(snap), len(elig), cfg["universe"]["price_min"], cfg["universe"]["price_max"]))


def check_edgar():
    from bot.signals.insider import cik_to_ticker_map, _session
    cfg = config.load()
    m = cik_to_ticker_map(_session(cfg["edgar_user_agent"]))
    return (len(m) > 5000, "SEC ticker map: {} companies".format(len(m)))


def check_dilution():
    cfg = config.load()
    from bot.signals.dilution import check_dilution as cd
    r = cd(cfg, "AAPL")
    return (isinstance(r, dict) and "alltime_filings" in r,
            "EDGAR offering query OK (AAPL lifetime offerings: {})".format(r.get("alltime_filings")))


def check_reddit():
    from bot.signals.reddit import fetch_mentions
    m = fetch_mentions(pages=1)
    top = sorted(m.items(), key=lambda kv: kv[1]["mentions"], reverse=True)[:1]
    return (len(m) > 0, "ApeWisdom: {} tickers, top {}".format(
        len(m), top[0][0] if top else "—"))


def check_quant_regime():
    r, d = risk_regime_probe()
    return (r is not None, "regime {} (VIX {})".format(r, d.get("vix")) if r
            else "quant regime unavailable")


def risk_regime_probe():
    from bot.signals.regime import quant_regime
    return quant_regime()


def check_research_fresh():
    r = risk.load_research()
    if not r:
        return (False, "no research.json yet")
    if r.get("_stale"):
        return (False, "STALE — last from {} (bot on neutral defaults)".format(r.get("date")))
    return (True, "fresh, dated {}, regime {}".format(r.get("date"), risk.regime(r)))


def check_finnhub():
    from bot.signals.finnhub_data import _key
    return (True, "key configured — enhanced earnings/sentiment active" if _key()
            else "no key (optional) — using Yahoo fallbacks")


def check_broker():
    from bot import broker_t212, config
    return broker_t212.health(config.load())


def check_alpaca():
    from bot import alpaca
    return alpaca.health()


def check_fda():
    from bot.signals.fda import recent_fda_activity
    # a known biotech to confirm the endpoint responds
    note = recent_fda_activity("Pfizer Inc")
    return (True, "openFDA reachable (keyless)" + (" — " + note if note else ""))


def check_macro():
    from bot.signals.macro import macro_signal, _key
    if not _key():
        return (True, "no FRED key (optional) — using Yahoo quant regime")
    tilt, detail = macro_signal()
    return (bool(detail), "FRED macro {} tilt {:+.2f}".format(detail, tilt) if detail
            else "FRED key set but no data")


def check_dashboard():
    from bot import dashboard
    path, _ = dashboard.generate()
    import os
    return (os.path.exists(path), "regenerated {}".format(os.path.basename(path)))


CHECKS = [
    ("Config", check_config), ("Ledger", check_ledger),
    ("Market data (Yahoo)", check_market_data), ("Universe filter", check_universe_filter),
    ("SEC EDGAR insider map", check_edgar), ("EDGAR dilution query", check_dilution),
    ("Reddit (ApeWisdom)", check_reddit), ("Quant regime", check_quant_regime),
    ("Daily research freshness", check_research_fresh), ("Finnhub", check_finnhub),
    ("Trading 212 broker", check_broker), ("Alpaca data feed", check_alpaca),
    ("openFDA catalysts", check_fda), ("FRED macro", check_macro),
    ("Dashboard generation", check_dashboard),
]


def run(send=True):
    results = []
    for name, fn in CHECKS:
        ok, detail = _try(fn)
        results.append((name, ok, detail))
        print("[{}] {} — {}".format("PASS" if ok else "FAIL", name, detail))

    n_pass = sum(1 for _, ok, _ in results if ok)
    n = len(results)
    lines = ["System health check — {}".format(
        dt.datetime.now().strftime("%a %d %b %Y, %H:%M")),
        "{}/{} subsystems healthy\n".format(n_pass, n)]
    for name, ok, detail in results:
        lines.append("{} {:<26} {}".format("✅" if ok else "❌", name, detail))
    lines.append("\nNote: a FAIL on 'Daily research freshness' just means the "
                 "research session hasn't run recently; the bot keeps trading on "
                 "its quant-regime fallback.")
    body = "\n".join(lines)

    if send:
        subj = "[bot health] {}/{} OK — {}".format(
            n_pass, n, "all systems go" if n_pass == n else "see report")
        notify.send_email(subj, body)
    return n_pass, n, body


if __name__ == "__main__":
    run()
