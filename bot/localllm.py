"""Local LLM enrichment worker — Ollama on the OptiPlex feeds Claude.

Reads the token-heavy raw text (SEC filings + fresh news) for the book and
top candidates, and uses a LOCAL quantised model (qwen2.5:7b via Ollama, CPU)
to digest each into structured flags: dilution language, going-concern,
offering/ATM terms, catalyst quality, a one-line summary. Writes
data/local_digest.json.

The point is DIVISION OF LABOUR, not replacement: the local model does the
cheap bulk reading (long 10-K/10-Q text that would cost Claude thousands of
tokens) and hands Claude a compact, structured digest to JUDGE. It also works
when Claude is throttled — a resilience layer. RESEARCH-ONLY into scoring
until the study validates it; the risk officer + critic read it as context.
"""
import datetime as dt
import json
import os
import urllib.request

from bot.config import DATA_DIR

OUT = os.path.join(DATA_DIR, "local_digest.json")
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5:7b"
NUM_THREAD = 10        # leave 2 of 12 cores for the OS + trading loop
NUM_CTX = 8192


def _ask(prompt, timeout=180):
    """One local completion, forced to JSON. None on any failure (fail-open)."""
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False, "format": "json",
        "options": {"num_thread": NUM_THREAD, "num_ctx": NUM_CTX,
                    "temperature": 0.1},
    }).encode()
    try:
        req = urllib.request.Request(OLLAMA, data=body,
                                     headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return json.loads(r.get("response", "") or "{}")
    except Exception:
        return None


def _sources(ticker):
    """Compact raw text for one ticker: recent news titles + latest EDGAR
    filing snippet. Kept short so local CPU inference stays quick."""
    chunks = []
    try:
        from bot import market
        heads = [n.get("title", "") for n in (market.ticker_news(ticker) or [])[:8]]
        if heads:
            chunks.append("Recent headlines:\n- " + "\n- ".join(h for h in heads if h))
    except Exception:
        pass
    try:
        # EDGAR full-text search: does this ticker have recent offering filings?
        url = ("https://efts.sec.gov/LATEST/search-index?q=%22{}%22&forms="
               "S-3,424B5,8-K&dateRange=custom").format(ticker)
        req = urllib.request.Request(
            "https://efts.sec.gov/LATEST/search-index?q=%22{}%22".format(ticker),
            headers={"User-Agent": "trading-bot research joshua.ive@gmail.com"})
        d = json.load(urllib.request.urlopen(req, timeout=15))
        hits = d.get("hits", {}).get("hits", [])[:5]
        forms = [h.get("_source", {}).get("file_type", "") for h in hits]
        if forms:
            chunks.append("Recent SEC form types on file: " + ", ".join(f for f in forms if f))
    except Exception:
        pass
    return "\n\n".join(chunks)


def _watch():
    import sqlite3
    con = sqlite3.connect(os.path.join(DATA_DIR, "ledger.db"))
    held = [r[0] for r in con.execute("SELECT ticker FROM positions WHERE status='open'")]
    last = con.execute("SELECT MAX(ts) FROM scan_candidates").fetchone()[0]
    cands = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM scan_candidates WHERE ts=? ORDER BY score DESC",
        (last,))][:6] if last else []
    con.close()
    return list(dict.fromkeys(held + cands))


def run():
    tickers = _watch()
    if not tickers:
        return {}
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "model": MODEL + " (local CPU via Ollama)", "tickers": {}}
    for t in tickers:
        src = _sources(t)
        if not src:
            continue
        prompt = (
            "You are a small-cap equity risk pre-screener. From the raw text "
            "below about {t}, extract ONLY what is stated — do not speculate. "
            "Return JSON: {{\"dilution_risk\":\"none|possible|active\","
            "\"going_concern\":true|false,\"catalyst\":\"<one phrase or 'none'>\","
            "\"sentiment\":\"bearish|neutral|bullish\",\"summary\":\"<=20 words\"}}."
            "\n\nRAW TEXT for {t}:\n{s}"
        ).format(t=t, s=src[:6000])
        d = _ask(prompt)
        if isinstance(d, dict) and d:
            out["tickers"][t] = {k: d.get(k) for k in
                                 ("dilution_risk", "going_concern", "catalyst",
                                  "sentiment", "summary")}
    out["note"] = ("Local-model digest of filings/news. Pre-screen for Claude, "
                   "NOT a score input until the study validates it. Fail-open: "
                   "empty when Ollama is down.")
    json.dump(out, open(OUT, "w"), indent=1)
    return out


if __name__ == "__main__":
    r = run()
    n = len(r.get("tickers", {}))
    print("local digest:", n, "tickers ->", OUT)
    for t, v in list(r.get("tickers", {}).items())[:5]:
        print("  {:6s} dilution={} sentiment={} — {}".format(
            t, v.get("dilution_risk"), v.get("sentiment"), (v.get("summary") or "")[:60]))
