"""One-off Trading 212 connection test — SAFE and demo-guarded.

  python -m bot.broker_check            # verify + show balance/positions only
  PLACE_TEST_ORDER=true python -m bot.broker_check   # + place a pending test order

Verifies the API key works, prints account cash + positions, and (optionally)
places a NON-EXECUTING limit order priced far below the market so a 'pending'
order shows up in the demo account for the user to confirm and cancel.

Hard guards:
- REFUSES to place any order unless broker.t212_environment == 'demo'.
- The test order is a limit ~50% below market → it cannot fill.
- Sized to ~$5 notional, always under max_order_value_usd, and skipped if the
  demo account lacks the free cash.
This module is run manually via the broker-check workflow; it is never part of
the automated trading loop.
"""
import os
import sys

from bot import config, broker_t212, market

TEST_TICKER = "AAPL"     # highly liquid → reliably resolves in T212's instrument list
TARGET_NOTIONAL = 5.0


def _probe_environments():
    """When auth fails, probe BOTH T212 environments AND several auth-header
    formats with the key, reporting only HTTP status (never the body/balance).
    Resolves whether this is our header format vs a wrong-env / invalid /
    IP-restricted key — without exposing any account data."""
    import base64
    import hashlib
    import requests
    key = broker_t212._api_key()
    if not key:
        print("probe       : no key reachable to probe")
        return
    # safe fingerprint (never the value): confirms the key arrives intact/whole.
    # A valid T212 key is ~30-40 alphanumeric chars with no whitespace.
    fp = hashlib.sha256(key.encode()).hexdigest()[:8]
    print("   key check   : len={} alnum={} whitespace={} sha256={}".format(
        len(key), key.isalnum(), any(c.isspace() for c in key), fp))
    # candidate auth schemes (T212 docs are inconsistent: raw key vs Basic)
    schemes = {
        "raw-key": key,
        "Bearer": "Bearer " + key,
        "Basic(key:)": "Basic " + base64.b64encode((key + ":").encode()).decode(),
    }
    print("probe       : testing auth formats x environments (status only)…")
    any200 = None
    for env, base_url in (("demo", broker_t212.BASE["demo"]),
                          ("live", broker_t212.BASE["live"])):
        for name, hdr in schemes.items():
            try:
                r = requests.get(base_url + "/api/v0/equity/account/cash",
                                 headers={"Authorization": hdr}, timeout=20)
                flag = "  <-- WORKS" if r.status_code == 200 else ""
                if r.status_code == 200 and not any200:
                    any200 = (env, name)
                print("   {:5} {:14} -> HTTP {}{}".format(env, name, r.status_code, flag))
            except Exception as e:
                print("   {:5} {:14} -> error {}".format(env, name, str(e)[:60]))
    if any200:
        print("   => our connector should use env='{}', auth='{}'".format(*any200))
    else:
        print("   => every format 401s on both envs = the KEY is invalid or "
              "IP-restricted (regenerate WITHOUT an IP restriction).")


def main():
    cfg = config.load()
    env = cfg.get("broker", {}).get("t212_environment", "demo")
    print("=== Trading 212 connection check ===")
    print("environment :", env)

    if not broker_t212.configured():
        print("RESULT: NO KEY reachable — T212_API_KEY is not set in this environment.")
        sys.exit(1)

    ok, detail = broker_t212.health(cfg)
    print("health      :", "OK" if ok else "FAIL", "-", detail)
    if not ok:
        _probe_environments()
        sys.exit(1)

    cash = broker_t212.account_cash(cfg) or {}
    free = float(cash.get("free") or 0)
    print("cash        : free ${:,.2f} | invested ${:,.2f} | total ${:,.2f} | open P/L ${:,.2f}".format(
        free, float(cash.get("invested") or 0), float(cash.get("total") or 0),
        float(cash.get("ppl") or 0)))

    pf = broker_t212.portfolio(cfg) or []
    print("positions   :", len(pf))
    for p in pf:
        print("   {} qty {} avg {} now {} pl {}".format(
            p.get("ticker"), p.get("quantity"), p.get("averagePrice"),
            p.get("currentPrice"), p.get("ppl")))

    if os.environ.get("PLACE_TEST_ORDER") != "true":
        print("\ntest order  : skipped (read-only check).")
        print("RESULT: connection OK — account is visible.")
        return

    # ---- optional NON-EXECUTING pending test order ----
    if env != "demo":
        print("\nRESULT: REFUSING to place a test order — environment is '{}', not 'demo'.".format(env))
        sys.exit(2)

    px = market.last_price(TEST_TICKER)
    if not px:
        print("\ntest order  : could not fetch a price for {} — skipped.".format(TEST_TICKER))
        sys.exit(3)

    limit = round(px * 0.5, 2)                 # far below market → cannot fill
    qty = round(TARGET_NOTIONAL / limit, 4)
    notional = qty * limit
    if free < notional + 1:
        print("\ntest order  : demo free cash ${:,.2f} too low for a ${:,.2f} test — skipped.".format(
            free, notional))
        print("RESULT: connection OK — account visible; top up demo cash in-app to test an order.")
        return

    # send to the DEMO account (fake money). In-memory only — config.json unchanged.
    cfg.setdefault("broker", {})["live_orders_enabled"] = True
    print("\ntest order  : placing NON-EXECUTING limit BUY {} x{} @ ${:.2f} "
          "(market ${:.2f}, ~50% below → will NOT fill)".format(TEST_TICKER, qty, limit, px))
    res = broker_t212.place_limit_order(cfg, TEST_TICKER, qty, limit,
                                        time_validity="GTC", dry_run=False)
    print("place result:", res)

    print("\npending orders now:")
    for o in broker_t212.list_orders(cfg) or []:
        print("   id {} {} {} qty {} limit {} status {}".format(
            o.get("id"), o.get("type"), o.get("ticker"),
            o.get("quantity"), o.get("limitPrice"), o.get("status")))
    print("\nRESULT: connection OK — a pending (non-fillable) test order is now in your "
          "DEMO account. Cancel it in the app, or ask me to cancel it.")


if __name__ == "__main__":
    main()
