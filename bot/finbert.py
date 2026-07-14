"""Local FinBERT sentiment worker — transformer NLP on the box, zero tokens.

Scores every headline in the rolling news feed with ProsusAI/finbert
(110M-param financial-sentiment model, CPU inference ~50ms/headline on the
OptiPlex). Complements the Claude agents: FinBERT is deterministic,
per-headline, and runs every 20 minutes for free; Claude interprets and
verifies at the story level every 15.

Writes data/finbert.json: per-ticker mean sentiment (-1..+1), label counts,
and the strongest positive/negative headline. RESEARCH DATA ONLY until the
study session validates it against outcomes (same rule as the screens) —
the scorer does NOT consume it yet.
"""
import datetime as dt
import json
import os

from bot.config import DATA_DIR

OUT = os.path.join(DATA_DIR, "finbert.json")
_model = {}


def _pipe():
    if "p" not in _model:
        from transformers import pipeline
        _model["p"] = pipeline("sentiment-analysis", model="ProsusAI/finbert",
                               truncation=True, max_length=128)
    return _model["p"]


def _headlines():
    """[(ticker, title)] from the rolling news cache (deduped)."""
    seen, out = set(), []
    try:
        rows = json.load(open(os.path.join(DATA_DIR, "cache",
                                           "headlines_rolling.json")))
        for h in rows:
            t = (h.get("ticker") or "").upper()
            title = (h.get("title") or "").strip()
            if t and title and (t, title) not in seen:
                seen.add((t, title))
                out.append((t, title))
    except Exception:
        pass
    # broaden the diet: fresh yfinance news for holdings + latest candidates
    try:
        import sqlite3
        from bot import market
        con = sqlite3.connect(os.path.join(DATA_DIR, "ledger.db"))
        held = [r[0] for r in con.execute(
            "SELECT ticker FROM positions WHERE status='open'")]
        last_ts = con.execute("SELECT MAX(ts) FROM scan_candidates").fetchone()[0]
        cands = [r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM scan_candidates WHERE ts=?",
            (last_ts,))] if last_ts else []
        con.close()
        for t in dict.fromkeys(held + cands):
            for n in (market.ticker_news(t) or [])[:6]:
                title = (n.get("title") or "").strip()
                if title and (t, title) not in seen:
                    seen.add((t, title))
                    out.append((t, title))
    except Exception:
        pass
    return out[:300]           # bound the batch; CPU does ~20/sec


def run():
    heads = _headlines()
    if not heads:
        return {}
    pipe = _pipe()
    results = pipe([h[1] for h in heads], batch_size=16)
    SIGN = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    per = {}
    for (tkr, title), r in zip(heads, results):
        s = SIGN.get(r["label"], 0.0) * float(r["score"])
        d = per.setdefault(tkr, {"scores": [], "best": None, "worst": None})
        d["scores"].append(s)
        if s > 0 and (d["best"] is None or s > d["best"][0]):
            d["best"] = (round(s, 3), title[:110])
        if s < 0 and (d["worst"] is None or s < d["worst"][0]):
            d["worst"] = (round(s, 3), title[:110])

    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "model": "ProsusAI/finbert (local CPU)",
           "headlines_scored": len(heads),
           "tickers": {}}
    for tkr, d in per.items():
        n = len(d["scores"])
        out["tickers"][tkr] = {
            "mean": round(sum(d["scores"]) / n, 3),
            "n": n,
            "best": d["best"], "worst": d["worst"],
        }
    out["note"] = ("Deterministic transformer sentiment, free and local. "
                   "NOT a score input yet — the study session must validate "
                   "mean-sentiment vs trade outcomes first.")
    json.dump(out, open(OUT, "w"), indent=1)
    # RAG SEED: append scored headlines to the permanent archive. Today this
    # is just rows in SQLite; once the corpus is large enough (50k+), it
    # becomes the retrieval base for "what happened the last N times a
    # headline like this hit?" precedent lookups.
    try:
        import sqlite3
        arc = sqlite3.connect(os.path.join(DATA_DIR, "news_archive.db"))
        arc.execute("CREATE TABLE IF NOT EXISTS headlines ("
                    "ts TEXT, ticker TEXT, title TEXT, sentiment REAL, "
                    "PRIMARY KEY(ticker, title))")
        now = out["generated"]
        for (tkr, title), r in zip(heads, results):
            s = SIGN.get(r["label"], 0.0) * float(r["score"])
            arc.execute("INSERT OR IGNORE INTO headlines VALUES (?,?,?,?)",
                        (now, tkr, title, round(s, 3)))
        arc.commit()
        arc.close()
    except Exception:
        pass
    return out


if __name__ == "__main__":
    r = run()
    print("finbert:", r.get("headlines_scored", 0), "headlines,",
          len(r.get("tickers", {})), "tickers ->", OUT)
    ranked = sorted(r.get("tickers", {}).items(), key=lambda kv: kv[1]["mean"])
    for t, v in (ranked[:3] + ranked[-3:]):
        print("  {:6s} mean {:+.2f} (n={})".format(t, v["mean"], v["n"]))
