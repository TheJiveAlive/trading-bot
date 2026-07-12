"""SQLite ledger: cash, positions, trades, and a decision log explaining
every action (or deliberate inaction) the bot takes."""
import datetime as dt
import json
import os
import sqlite3

from bot.config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "ledger.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY, shares INTEGER, avg_cost REAL,
    opened_at TEXT, high_water_mark REAL, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT, side TEXT,
    shares INTEGER, price REAL, value REAL, mode TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS scan_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT,
    score REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, equity REAL, cash REAL);
CREATE TABLE IF NOT EXISTS trade_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT, parts TEXT,
    catalyst TEXT);
CREATE TABLE IF NOT EXISTS catalyst_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT,
    catalyst TEXT, pnl_pct REAL);
CREATE TABLE IF NOT EXISTS signal_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT,
    signal TEXT, contribution REAL, pnl_pct REAL);
"""


def connect():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    """Add columns to pre-existing tables (CREATE IF NOT EXISTS won't alter them)."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(trade_signals)")]
    if "catalyst" not in cols:
        con.execute("ALTER TABLE trade_signals ADD COLUMN catalyst TEXT")
        con.commit()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(con, key, value):
    con.execute("INSERT INTO meta (key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))


def cash(con):
    return float(get_meta(con, "cash", "0"))


def set_cash(con, amount):
    set_meta(con, "cash", round(amount, 2))


def log_decision(con, kind, detail):
    con.execute("INSERT INTO decisions (ts,kind,detail) VALUES (?,?,?)",
                (now(), kind, detail))


def log_candidates(con, candidates):
    for c in candidates:
        con.execute(
            "INSERT INTO scan_candidates (ts,ticker,score,detail) VALUES (?,?,?,?)",
            (now(), c["ticker"], c["score"], json.dumps(c)))


def apply_monthly_deposit(con, cfg):
    """Credit the monthly deposit once per calendar month on/after deposit day."""
    if cfg.get("monthly_deposit_usd", 0) <= 0:
        return False    # disabled (e.g. T212 demo rehearsal — no real deposits)
    today = dt.date.today()
    tag = today.strftime("%Y-%m")
    if today.day < cfg["deposit_day_of_month"]:
        return False
    if get_meta(con, "last_deposit_month") == tag:
        return False
    set_cash(con, cash(con) + cfg["monthly_deposit_usd"])
    set_meta(con, "last_deposit_month", tag)
    log_decision(con, "deposit", "Credited ${:.2f} monthly deposit for {}".format(
        cfg["monthly_deposit_usd"], tag))
    return True


def open_positions(con):
    rows = con.execute(
        "SELECT ticker, shares, avg_cost, opened_at, high_water_mark "
        "FROM positions WHERE status='open'").fetchall()
    return [{"ticker": r[0], "shares": r[1], "avg_cost": r[2],
             "opened_at": r[3], "high_water_mark": r[4]} for r in rows]


def record_buy(con, ticker, shares, price, mode, reason):
    value = shares * price
    con.execute("INSERT INTO trades (ts,ticker,side,shares,price,value,mode,reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (now(), ticker, "buy", shares, price, value, mode, reason))
    existing = con.execute("SELECT shares, avg_cost, status FROM positions WHERE ticker=?",
                           (ticker,)).fetchone()
    if existing and existing[2] == "open":
        old_shares, old_cost = existing[0], existing[1]
        new_shares = old_shares + shares
        new_cost = (old_shares * old_cost + shares * price) / new_shares
        con.execute("UPDATE positions SET shares=?, avg_cost=? WHERE ticker=?",
                    (new_shares, new_cost, ticker))
    else:
        con.execute("INSERT INTO positions (ticker,shares,avg_cost,opened_at,high_water_mark,status) "
                    "VALUES (?,?,?,?,?,'open') "
                    "ON CONFLICT(ticker) DO UPDATE SET shares=excluded.shares, "
                    "avg_cost=excluded.avg_cost, opened_at=excluded.opened_at, "
                    "high_water_mark=excluded.high_water_mark, status='open'",
                    (ticker, shares, price, now(), price))
    set_cash(con, cash(con) - value)
    log_decision(con, "buy", "{} {} @ ${:.2f} (${:.2f}) — {}".format(
        shares, ticker, price, value, reason))


def record_sell(con, ticker, shares, price, mode, reason):
    value = shares * price
    con.execute("INSERT INTO trades (ts,ticker,side,shares,price,value,mode,reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (now(), ticker, "sell", shares, price, value, mode, reason))
    con.execute("UPDATE positions SET status='closed' WHERE ticker=?", (ticker,))
    set_cash(con, cash(con) + value)
    log_decision(con, "sell", "{} {} @ ${:.2f} (${:.2f}) — {}".format(
        shares, ticker, price, value, reason))


def update_high_water_mark(con, ticker, price):
    con.execute("UPDATE positions SET high_water_mark=MAX(high_water_mark,?) "
                "WHERE ticker=? AND status='open'", (price, ticker))


def record_equity(con, equity, cash_now):
    con.execute("INSERT INTO equity_history (ts,equity,cash) VALUES (?,?,?)",
                (now(), round(equity, 2), round(cash_now, 2)))


def buys_this_week(con):
    monday = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    row = con.execute("SELECT COUNT(*) FROM trades WHERE side='buy' AND ts >= ?",
                      (monday.isoformat(),)).fetchone()
    return row[0]


def buys_today(con):
    today = dt.date.today().isoformat()
    row = con.execute("SELECT COUNT(*) FROM trades WHERE side='buy' AND ts >= ?",
                      (today,)).fetchone()
    return row[0]
