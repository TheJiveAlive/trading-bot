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


def _plain(t212_ticker, cfg=None):
    """Map a T212 instrument id back to OUR symbol. T212's internal symbols can
    differ from the market ticker (WRAP trades as WRTC_US_EQ, CAI as CAI1_US_EQ)
    — the instrument metadata's shortName is the real symbol, so use the
    reverse of instrument_map() and only fall back to prefix-stripping."""
    t = (t212_ticker or "").upper()
    if cfg is not None:
        try:
            rev = {v: k for k, v in broker_t212.instrument_map(cfg).items()}
            if t in rev:
                return rev[t]
        except Exception:
            pass
    return t.split("_")[0]


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
    # tickers whose buy order the broker REJECTED *recently* (phantom positions
    # the ledger recorded optimistically but that never actually filled).
    # ONLY fresh rejections count: a stale error entry must never kill a
    # position that later re-bought and genuinely filled.
    rejected = set()
    try:
        po = os.path.join(DATA_DIR, "pending_orders.json")
        if os.path.exists(po):
            with open(po) as f:
                orders = json.load(f)
            now = dt.datetime.now(dt.timezone.utc)
            fresh = []
            for o in orders:
                try:
                    age = (now - dt.datetime.fromisoformat(
                        str(o.get("ts", "")).replace("Z", "+00:00"))).total_seconds()
                except Exception:
                    age = 1e9
                if age < 24 * 3600:
                    fresh.append(o)              # keep <24h entries in the file
                if o.get("side") == "buy" and o.get("error") and age < 1800:
                    rejected.add((o.get("ticker") or "").upper())
            if len(fresh) != len(orders):        # prune stale entries
                with open(po, "w") as f:
                    json.dump(fresh, f, indent=2)
    except Exception:
        pass
    rows = []
    for tkr in sorted(set(ledger_pos) | set(broker_pos)):
        lp = ledger_pos.get(tkr)
        bp = broker_pos.get(tkr)
        lsh = lp["shares"] if lp else None
        bsh = bp["shares"] if bp else None
        if lsh is None:
            # broker holds it, ledger doesn't — the broker is the source of
            # truth, so ADOPT it (covers fills the ledger lost track of)
            try:
                con.execute(
                    "INSERT INTO positions (ticker,shares,avg_cost,opened_at,"
                    "high_water_mark,status) VALUES (?,?,?,?,?,'open') "
                    "ON CONFLICT(ticker) DO UPDATE SET shares=excluded.shares, "
                    "avg_cost=excluded.avg_cost, status='open'",
                    (tkr, float(bsh), float(bp.get("avg_price") or 0),
                     dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                     float(bp.get("avg_price") or 0)))
                ledger.log_decision(con, "recon_adopt",
                                    "{}: held at Trading 212 ({} sh @ ${:.2f}) but missing "
                                    "from the ledger — adopted (broker is truth)".format(
                                        tkr, bsh, bp.get("avg_price") or 0))
                con.commit()
                rows.append({"ticker": tkr, "ledger_shares": bsh,
                             "broker_shares": bsh, "status": "adopted"})
                continue
            except Exception:
                status = "broker_only"
        elif bsh is None and tkr in rejected:
            # broker rejected the buy — it never filled. Remove the phantom so
            # the ledger matches reality (cash is already broker-synced).
            con.execute("DELETE FROM positions WHERE ticker=? AND status='open'", (tkr,))
            con.execute("DELETE FROM trades WHERE id IN "
                        "(SELECT id FROM trades WHERE ticker=? AND side='buy' "
                        "ORDER BY id DESC LIMIT 1)", (tkr,))
            ledger.log_decision(con, "recon_remove",
                                "{}: broker rejected the order (never filled) — "
                                "phantom position removed to match Trading 212".format(tkr))
            con.commit()
            rows.append({"ticker": tkr, "ledger_shares": lsh,
                         "broker_shares": None, "status": "removed_phantom"})
            continue
        elif bsh is None:
            # if our own ledger says the LAST trade for this ticker was a SELL,
            # an open row is a zombie (e.g. re-adopted during broker fill
            # latency) — close it to match reality
            last = con.execute("SELECT side FROM trades WHERE ticker=? "
                               "ORDER BY id DESC LIMIT 1", (tkr,)).fetchone()
            if last and last[0] == "sell":
                con.execute("UPDATE positions SET status='closed' WHERE ticker=?", (tkr,))
                ledger.log_decision(con, "recon_close",
                                    "{}: sold (last trade) but row re-opened by a "
                                    "fill-latency race — closed to match broker".format(tkr))
                con.commit()
                rows.append({"ticker": tkr, "ledger_shares": lsh,
                             "broker_shares": None, "status": "closed_zombie"})
                continue
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


def _sync_ledger_cash(cash, state):
    """Broker = source of truth for cash too. The ledger keeps USD (stocks trade
    in USD) while the T212 account is GBP; convert the broker's free cash at the
    shared FX rate and adopt it when the ledger has drifted >2% (fills at T212
    include their own FX conversion, so drift is expected). Logged as cash_sync."""
    try:
        free = float((cash or {}).get("free") or 0)
        if free <= 0:
            return
        from bot import fx
        if state.get("account_currency", "GBP") == "GBP":
            free_usd = free * fx.usd_per_gbp()
        else:
            free_usd = free
        con = ledger.connect()
        cur = ledger.cash(con)
        if cur > 0 and abs(free_usd - cur) / cur > 0.02:
            ledger.set_cash(con, free_usd)
            ledger.log_decision(con, "cash_sync",
                                "adopted broker free cash ${:.2f} (ledger had ${:.2f})".format(
                                    free_usd, cur))
        con.commit()
        con.close()
    except Exception:
        pass


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
        # T212 account cash/P-L figures come back in the ACCOUNT currency
        "account_currency": cfg.get("broker", {}).get("account_currency", "GBP"),
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
                "ticker": _plain(p.get("ticker", ""), cfg),
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
        _sync_ledger_cash(cash, state)
        state["detail"] = "{} account reachable: {} position(s), free {}{}".format(
            env, len(positions),
            "£" if state["account_currency"] == "GBP" else "$",
            (cash or {}).get("free", "?"))
    except Exception as e:
        state["detail"] = "Trading 212 error: {}".format(e).replace("\n", " ")[:200]

    _write(state)
    return state


if __name__ == "__main__":
    s = sync(force=True)
    print("broker sync [{}]: {}".format("OK" if s["ok"] else "idle/err", s["detail"]))
