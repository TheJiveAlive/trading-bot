"""Pre-buy critic: Claude reviews each specific buy BEFORE execution.

The hourly intel sweeps the tape; this is the opposite — a targeted second
opinion on ONE candidate the bot is about to buy (2-6 calls/day). It runs the
local Claude CLI (subscription auth from the vault), no tools, one turn, and
must answer in strict JSON.

FAIL-OPEN by design: if Claude is unreachable/slow/non-JSON, the buy proceeds —
the critic is an advisory layer on top of the hard vetoes, never a dependency.
A veto is logged (kind='critic_veto') and surfaces on the dashboard + monitor.
"""
import json
import os
import subprocess

from bot.config import DATA_DIR


def _token():
    for path in (os.path.join(DATA_DIR, "secrets.json"),
                 os.path.expanduser("~/.bot/secrets.json")):
        try:
            with open(path) as f:
                t = (json.load(f).get("claude_code_oauth_token") or "").strip()
            if t:
                return t
        except Exception:
            continue
    return None


def enabled(cfg):
    return bool(cfg.get("critic", {}).get("enabled")) and _token() is not None


def _ml_context(ticker):
    """One line of local-ML context for the reviewed ticker: FinBERT mean
    sentiment, Lorentzian k-NN score, and the quant regime state. Fail-silent
    — the critic worked without these before 2026-07-14."""
    import os
    from bot.config import DATA_DIR
    bits = []
    try:
        fb = json.load(open(os.path.join(DATA_DIR, "finbert.json")))
        v = fb.get("tickers", {}).get(ticker)
        if v:
            bits.append("FinBERT sentiment {:+.2f} over {} headlines".format(
                v["mean"], v["n"]))
    except Exception:
        pass
    try:
        lz = json.load(open(os.path.join(DATA_DIR, "lorentzian.json")))
        v = lz.get("lookup", {}).get(ticker)
        if v:
            bits.append("Lorentzian kNN {:+.2f}".format(v["score"]))
    except Exception:
        pass
    try:
        qr = json.load(open(os.path.join(DATA_DIR, "quant_regime.json")))
        bits.append("quant regime {} (hmm {})".format(
            qr.get("state"), qr.get("hmm_state")))
    except Exception:
        pass
    try:
        ld = json.load(open(os.path.join(DATA_DIR, "local_digest.json")))
        v = ld.get("tickers", {}).get(ticker)
        if v:
            bits.append("local-LLM: dilution {} / {} / {}".format(
                v.get("dilution_risk"), v.get("sentiment"),
                (v.get("summary") or "")[:50]))
    except Exception:
        pass
    return "; ".join(bits) or "no local-ML data"


def review_buy(cfg, cand, confluence_detail, headlines=None):
    """(approved: bool, note: str). Approves on any failure (fail-open)."""
    heads = "; ".join(h.get("title", "")[:70] for h in (headlines or [])[:3]) or "none cached"
    prompt = (
        "You are the final pre-trade risk reviewer for an automated small-cap bot. "
        "It is about to BUY {t} (~${n:.0f} notional, demo account). "
        "Composite score {s} from signal parts {p}. Confluence checks: {c}. "
        "Recent headlines: {h}. Local ML: {ml}. "
        "Respond with ONLY this JSON, nothing else: "
        '{{"verdict":"approve"|"veto","confidence":"high"|"medium"|"low","reason":"<=25 words"}}. '
        "Veto ONLY for: classic pump pattern, dilution/offering risk the signals "
        "missed, a stale or misread catalyst, or an obvious data error. "
        "When in doubt, approve — the bot's hard vetoes already ran."
    ).format(t=cand["ticker"], n=cand.get("notional", 0), s=cand["score"],
             p=json.dumps(cand.get("parts", {})), c=confluence_detail[:300], h=heads,
             ml=_ml_context(cand["ticker"]))

    env = dict(os.environ)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = _token()
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-opus-4-8",
             "--output-format", "json",
             "--allowedTools", "", "--max-turns", "1"],
            capture_output=True, text=True, timeout=int(
                cfg.get("critic", {}).get("timeout_s", 90)), env=env)
        out = json.loads(r.stdout)
        text = out.get("result", "")
        start, end = text.find("{"), text.rfind("}")
        verdict = json.loads(text[start:end + 1])
        v = (verdict.get("verdict") or "approve").lower()
        note = "critic {} ({}): {}".format(
            v, verdict.get("confidence", "?"), verdict.get("reason", ""))[:180]
        return (v != "veto", note)
    except Exception as e:
        return (True, "critic unavailable ({}) — fail-open".format(
            str(e)[:60]))
