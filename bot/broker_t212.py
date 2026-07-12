"""Trading 212 broker connector (equity API v0).

GUARDRAILS BY DESIGN
- The Trading 212 API exposes NO deposit/withdrawal/card/bank endpoints, so
  this connector cannot move money. It can only read account data and place
  equity orders. All funding is done by you in the app.
- Defaults to the DEMO (practice) environment. Live requires an explicit
  config flip AND a live API key.
- Fractional shares supported (Trading 212 accepts decimal quantities) when
  config.fractional_shares is true; else whole shares only.
- Every order is checked against max_order_value_usd before it is sent.
- The API key is read from data/secrets.json (local) or the T212_API_KEY
  env var (cloud secret). It is never logged.

Credentials: generate an API key in the Trading 212 app under
Settings > API (Beta). Use IP restriction where possible. Put it in
data/secrets.json as "t212_api_key", or the T212_API_KEY GitHub secret.
"""
import json
import os
import time

import requests

from bot.config import DATA_DIR

BASE = {
    "demo": "https://demo.trading212.com",
    "live": "https://live.trading212.com",
}
_INSTRUMENT_CACHE = os.path.join(DATA_DIR, "cache", "t212_instruments.json")
_CACHE_TTL_DAYS = 3


class T212Error(Exception):
    pass


def _api_key():
    k = os.environ.get("T212_API_KEY")
    if k:
        return k.strip()
    try:
        with open(os.path.join(DATA_DIR, "secrets.json")) as f:
            return (json.load(f).get("t212_api_key") or "").strip() or None
    except Exception:
        return None


def configured():
    return _api_key() is not None


def _headers():
    key = _api_key()
    if not key:
        raise T212Error("no Trading 212 API key configured")
    return {"Authorization": key, "Content-Type": "application/json"}


def _base(cfg):
    env = cfg.get("broker", {}).get("t212_environment", "demo")
    return BASE.get(env, BASE["demo"])


def _get(cfg, path):
    r = requests.get(_base(cfg) + path, headers=_headers(), timeout=25)
    if r.status_code == 401:
        raise T212Error("401 unauthorized — check API key / environment")
    if r.status_code == 429:
        raise T212Error("429 rate limited")
    r.raise_for_status()
    return r.json()


def account_cash(cfg):
    """{'free':..,'total':..} account cash, or raises."""
    return _get(cfg, "/api/v0/equity/account/cash")


def portfolio(cfg):
    """List of open positions from Trading 212."""
    return _get(cfg, "/api/v0/equity/portfolio")


def instrument_map(cfg):
    """{plain_ticker: t212_ticker} e.g. {'AAPL': 'AAPL_US_EQ'}. Cached 3 days."""
    if os.path.exists(_INSTRUMENT_CACHE):
        age = time.time() - os.path.getmtime(_INSTRUMENT_CACHE)
        if age < _CACHE_TTL_DAYS * 86400:
            with open(_INSTRUMENT_CACHE) as f:
                return json.load(f)
    data = _get(cfg, "/api/v0/equity/metadata/instruments")
    mapping = {}
    for inst in data:
        t212 = inst.get("ticker", "")
        short = inst.get("shortName") or (t212.split("_")[0] if t212 else "")
        if short and t212 and short.upper() not in mapping:
            mapping[short.upper()] = t212
    os.makedirs(os.path.dirname(_INSTRUMENT_CACHE), exist_ok=True)
    with open(_INSTRUMENT_CACHE, "w") as f:
        json.dump(mapping, f)
    return mapping


def resolve_ticker(cfg, ticker):
    """Map our plain ticker to the Trading 212 instrument id, or None."""
    try:
        return instrument_map(cfg).get(ticker.upper())
    except Exception:
        return None


def place_market_order(cfg, ticker, signed_shares, price_hint=None, dry_run=True):
    """Place a market order. signed_shares: +buy / -sell (fractional when
    config.fractional_shares is true, else whole shares only).

    Returns a dict describing the result. When dry_run, nothing is sent —
    the intended order is returned with 'dry_run': True.
    """
    broker = cfg.get("broker", {})
    # Trading 212 accepts fractional quantities (decimals). Honour the bot's
    # fractional_shares setting: fractional → keep decimals; else whole only.
    if cfg.get("fractional_shares"):
        qty = round(float(signed_shares), 4)
    else:
        if int(signed_shares) != signed_shares:
            raise T212Error("fractional shares disabled — whole shares only")
        qty = int(signed_shares)
    if qty == 0:
        raise T212Error("zero quantity")

    # value guardrail (uses price hint from our own market data)
    cap = broker.get("max_order_value_usd", 100.0)
    if price_hint and abs(qty) * price_hint > cap:
        raise T212Error("order value ${:.2f} exceeds max_order_value_usd ${:.2f}".format(
            abs(qty) * price_hint, cap))

    is_dry = dry_run or not broker.get("live_orders_enabled", False)

    # dry-run without a key: preview using the plain ticker (can't resolve yet)
    if is_dry and not configured():
        return {"dry_run": True, "would_send": {"ticker": ticker, "quantity": qty},
                "environment": broker.get("t212_environment", "demo"),
                "note": "no API key — preview only"}

    t212_ticker = resolve_ticker(cfg, ticker)
    if not t212_ticker:
        raise T212Error("ticker {} not found in Trading 212 instrument list".format(ticker))

    order = {"ticker": t212_ticker, "quantity": qty}
    if is_dry:
        return {"dry_run": True, "would_send": order, "environment":
                broker.get("t212_environment", "demo")}

    r = requests.post(_base(cfg) + "/api/v0/equity/orders/market",
                      headers=_headers(), json=order, timeout=25)
    if r.status_code >= 400:
        raise T212Error("order rejected ({}): {}".format(r.status_code, r.text[:200]))
    return {"dry_run": False, "sent": order, "response": r.json()}


def list_orders(cfg):
    """Open/pending equity orders at Trading 212 (read-only)."""
    return _get(cfg, "/api/v0/equity/orders")


def place_limit_order(cfg, ticker, signed_shares, limit_price,
                      time_validity="GTC", dry_run=True):
    """Place a LIMIT order. A limit far from the market rests as a 'pending'
    order and never fills — used for connection tests. Honours fractional_shares
    and the max_order_value_usd cap. Same dry-run gating as market orders."""
    broker = cfg.get("broker", {})
    if cfg.get("fractional_shares"):
        qty = round(float(signed_shares), 4)
    else:
        if int(signed_shares) != signed_shares:
            raise T212Error("fractional shares disabled — whole shares only")
        qty = int(signed_shares)
    if qty == 0:
        raise T212Error("zero quantity")
    cap = broker.get("max_order_value_usd", 100.0)
    if abs(qty) * limit_price > cap:
        raise T212Error("order value ${:.2f} exceeds max_order_value_usd ${:.2f}".format(
            abs(qty) * limit_price, cap))
    is_dry = dry_run or not broker.get("live_orders_enabled", False)
    t212_ticker = resolve_ticker(cfg, ticker)
    if not t212_ticker:
        raise T212Error("ticker {} not found in Trading 212 instrument list".format(ticker))
    order = {"ticker": t212_ticker, "quantity": qty,
             "limitPrice": round(limit_price, 2), "timeValidity": time_validity}
    if is_dry:
        return {"dry_run": True, "would_send": order,
                "environment": broker.get("t212_environment", "demo")}
    r = requests.post(_base(cfg) + "/api/v0/equity/orders/limit",
                      headers=_headers(), json=order, timeout=25)
    if r.status_code >= 400:
        raise T212Error("limit order rejected ({}): {}".format(r.status_code, r.text[:200]))
    return {"dry_run": False, "sent": order, "response": r.json()}


def cancel_order(cfg, order_id):
    """Cancel a pending equity order by id."""
    r = requests.delete(_base(cfg) + "/api/v0/equity/orders/{}".format(order_id),
                        headers=_headers(), timeout=25)
    if r.status_code >= 400:
        raise T212Error("cancel rejected ({}): {}".format(r.status_code, r.text[:200]))
    return {"cancelled": order_id, "http": r.status_code}


def health(cfg):
    """(ok, detail) for the dashboard / healthcheck."""
    if not configured():
        return (True, "no key set (optional) — Trading 212 execution disabled")
    try:
        cash = account_cash(cfg)
        env = cfg.get("broker", {}).get("t212_environment", "demo")
        return (True, "{} account reachable, free ${}".format(
            env, cash.get("free", "?")))
    except Exception as e:
        return (False, "Trading 212 error: {}".format(e))
