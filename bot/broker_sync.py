"""Pull the REAL Trading 212 account state (cash + open positions) into
data/broker_state.json so the dashboard can present the BROKER as the single
source of truth — reconciled against the local ledger.

READ-ONLY. This module never places, modifies or cancels an order. It only
GETs account data. When no API key is configured it writes an "idle" state and
the dashboard keeps showing the paper ledger, so nothing breaks pre-activation.

Self-throttled: re-uses the cached file if it was refreshed within
_MIN_INTERVAL_S, so it is safe to call often (dashboard renders, session loops)
without tripping Trading 212's rate limits.
"""
import datetime as dt
import json
import os

from bot.config import DATA_DIR
from bot import broker_t212, config, ledger

BROKER_STATE = os.path.join(DATA_DIR, "broker_state.json")
_MIN_INTERVAL_S = 45


def _now_z():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _plain(t212_ticker):
    """'AAPL_US_EQ' -> 'AAPL'. Trading 212 suffixes the exchange/type."""
    return (t212_ticker or "").split("_")[0].upper()


def _write(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BROKER_STATE, "w") as f:
        json.dump(state, f, indent=2)


def _fresh_enough():
    """Throttle by the 'generated' timestamp INSIDE the file — file mtime lies
    on CI (git checkout stamps the committed, possibly-stale file as brand new).
    Also never trust a cached 'no key' state when a key IS available now."""
    if not os.path.exists(BROKER_STATE):
        return False
    try:
        with open(BROKER_STATE) as f:
            s = json.load(f)
        if not s.get("configured") and broker_t212.configured():
            return False    # stale pre-key state; a key exists now — refresh
        gen = dt.datetime.fromisoformat(s["generated"].replace("Z", "+00:00"))
        age = (dt.datetime.now(dt.timezone.utc) - gen).total_seconds()
        return 0 <= age < _MIN_INTERVAL_S
    except Exception:
        return False


def _reconcile(broker_positions):
    """Compare what the ledger THINKS we hold with what the broker ACTUALLY
    holds. Returns a list of {ticker, ledger_shares, broker_shares, status}.

    Fill sync: when both sides agree on the shares but the broker's average
    price differs >0.5% from the ledger's, the broker's REAL fill price is
    adopted into the ledger (broker = source of truth) and logged."""
    con = ledger.connect()
    ledger_pos = {p["ticker"].upper(): p for p in ledger.open_positions(con)}
    broker_pos = {p["ticker"]: p for p in broker_positions}
    rows = []
    for tkr in sorted(set(ledger_pos) | set(broker_pos)):
        lp = ledger_pos.get(tkr)
        bp = broker_pos.get(tkr)
        lsh = lp["shares"] if lp else None
        bsh = bp["shares"] if bp else None
        if lsh is None:
            status = "broker_only"          # broker holds it, ledger doesn't
        elif bsh is None:
            status = "ledger_only"          # ledger thinks we hold it, broker doesn't
        elif abs(float(lsh) - float(bsh)) > max(1e-4, abs(float(lsh)) * 0.01):
            status = "drift"                 # both hold it but sizes disagree >1%
        else:
            status = "match"
            # adopt the broker's true fill price when it disagrees with our estimate
            l_avg, b_avg = lp.get("avg_cost"), bp.get("avg_price")
            if l_avg and b_avg and abs(b_avg - l_avg) / l_avg > 0.005:
                con.execute("UPDATE positions SET avg_cost=? WHERE ticker=? AND status='open'",
                            (float(b_avg), tkr))
                ledger.log_decision(con, "fill_sync",
                                    "{}: adopted broker fill ${:.4f} (ledger estimated ${:.4f})".format(
                                        tkr, b_avg, l_avg))
                status = "fill_synced"
        rows.append({"ticker": tkr, "ledger_shares": lsh,
                     "broker_shares": bsh, "status": status})
    con.commit()
    con.close()
    return rows


def sync(cfg=None, force=False):
    """Refresh data/broker_state.json from Trading 212. Best-effort: on any
    error it writes an error state rather than raising, so callers (dashboard,
    workflows) never break because the broker was briefly unreachable."""
    cfg = cfg or config.load()
    if not force and _fresh_enough():
        try:
            with open(BROKER_STATE) as f:
                return json.load(f)
        except Exception:
            pass

    env = cfg.get("broker", {}).get("t212_environment", "demo")
    state = {
        "generated": _now_z(),
        "environment": env,
        "configured": broker_t212.configured(),
        "live_orders_enabled": bool(cfg.get("broker", {}).get("live_orders_enabled")),
        "mode": cfg.get("mode"),
        "ok": False,
        "detail": "",
        "cash": None,
        "positions": [],
        "reconciliation": [],
    }

    if not broker_t212.configured():
        state["detail"] = ("no T212 API key set — broker sync idle "
                           "(dashboard is showing the paper ledger)")
        _write(state)
        return state

    try:
        cash = broker_t212.account_cash(cfg)
        pf = broker_t212.portfolio(cfg)
        positions = []
        for p in pf or []:
            positions.append({
                "ticker": _plain(p.get("ticker", "")),
                "t212_ticker": p.get("ticker", ""),
                "shares": p.get("quantity"),
                "avg_price": p.get("averagePrice"),
                "current_price": p.get("currentPrice"),
                "pnl": p.get("ppl"),
            })
        state["ok"] = True
        state["cash"] = cash
        state["positions"] = positions
        state["reconciliation"] = _reconcile(positions)
        state["detail"] = "{} account reachable: {} position(s), free ${}".format(
            env, len(positions), (cash or {}).get("free", "?"))
    except Exception as e:
        state["detail"] = "Trading 212 error: {}".format(e).replace("\n", " ")[:200]

    _write(state)
    return state


if __name__ == "__main__":
    s = sync(force=True)
    print("broker sync [{}]: {}".format("OK" if s["ok"] else "idle/err", s["detail"]))
